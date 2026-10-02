"""``sync_sis_account`` use case (docs/01, "SIS integration").

1. sign in to the SIS with the stored (encrypted) password and fetch the schedule
2. exams -> upsert ``Item(type=exam, source=sis)``; lecture occurrences -> upsert
   weekly ``LectureSchedule(source=sis)`` rows, expanded by the lecture service
3. link both to ``Course`` by course code when the student has a matching active
   enrollment; fill an empty ``Enrollment.tutor_name`` from the timetable lecturer
4. future exams / timetables gone from the SIS -> soft delete + cancel reminders
   (exams) or remove future occurrences (timetables); past rows stay as history
5. write a ``SisSyncLog``; on invalid credentials: mark the account, send one
   "reconnect" notification and stop syncing it.

All SIS calls happen before the database transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import SisInvalidCredentials, SisUnavailable
from apps.core.i18n import render_in
from apps.notifications.models import Notification
from apps.notifications.protocols import Message, NotificationChannel
from apps.notifications.services.history import notify_user
from apps.reminders.protocols import ReminderScheduler
from apps.schedule.models import Enrollment, Item, ItemSource, ItemType, LectureSchedule
from apps.schedule.services.lectures import (
    expand_lecture_schedule,
    regenerate_lecture_schedule,
    remove_lecture_schedule,
)
from apps.sis.models import SisAccount, SisSyncLog
from apps.sis.protocols import SisClient, SisScheduleEntry
from apps.sis.services.mappers import (
    ExamData,
    TimetableData,
    map_exams,
    map_timetable,
    normalize_code,
)

RECONNECT_TITLE = _("Reconnect the SIS")
RECONNECT_BODY = _(
    "Your SIS password no longer works. Reconnect it in Settings to keep your exams "
    "and lectures up to date."
)
INVALID_CREDENTIALS_ERROR = "invalid_credentials"

_EXAM_FIELDS = ("course_id", "title", "location", "scheduled_at", "ends_at")
_SCHEDULE_FIELDS = (
    "course_id",
    "title",
    "weekdays",
    "start_time",
    "duration_minutes",
    "location",
    "starts_on",
    "ends_on",
)


@dataclass(frozen=True)
class SisSyncResult:
    status: str  # "success" | "failed" | "skipped"
    items_created: int = 0
    items_updated: int = 0
    items_removed: int = 0
    error: str = ""


@dataclass
class _Counts:
    created: int = 0
    updated: int = 0
    removed: int = 0


def _local_zone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Africa/Cairo")


def _code_tokens(code: str) -> set[str]:
    upper = code.upper()
    tokens = {normalize_code(t) for t in upper.replace("_", " ").replace("-", " ").split()}
    return {t for t in tokens if t} | {normalize_code(upper)}


class _CourseIndex:
    """SIS course code -> the student's active enrollment with that code."""

    def __init__(self, user_id: Any) -> None:
        self._enrollments = list(
            Enrollment.objects.filter(user_id=user_id, is_active=True).select_related("course")
        )

    def find(self, sis_code: str) -> Enrollment | None:
        wanted = normalize_code(sis_code)
        if not wanted:
            return None
        for enrollment in self._enrollments:
            if wanted in _code_tokens(enrollment.course.code):
                return enrollment
        return None


class SyncSisAccount:
    def __init__(
        self,
        client: SisClient,
        scheduler: ReminderScheduler,
        channels: Mapping[str, NotificationChannel],
        now: Callable[[], datetime] = timezone.now,
    ) -> None:
        self._client = client
        self._scheduler = scheduler
        self._channels = channels
        self._now = now

    def __call__(self, account: SisAccount) -> SisSyncResult:
        if account.status not in (SisAccount.Status.ACTIVE, SisAccount.Status.ERROR):
            return SisSyncResult(status="skipped")
        started_at = self._now()
        try:
            session = self._client.login(account.username, account.get_password())
            entries = self._client.schedule(session)
        except SisInvalidCredentials:
            self._mark_invalid(account)
            return self._log_failure(account, started_at, INVALID_CREDENTIALS_ERROR)
        except SisUnavailable as exc:
            error = str(exc.details.get("sis_error") or "sis_unavailable")
            account.status = SisAccount.Status.ERROR
            account.last_sync_error = error
            account.save(update_fields=["status", "last_sync_error", "updated_at"])
            return self._log_failure(account, started_at, error)
        return self._apply(account, entries, started_at)

    # --- steps ----------------------------------------------------------------------

    def _apply(
        self, account: SisAccount, entries: list[SisScheduleEntry], started_at: datetime
    ) -> SisSyncResult:
        language = account.user.language
        exams = map_exams(entries, zone=_local_zone(), language=language)
        timetable = map_timetable(entries, language=language)
        counts = _Counts()
        with transaction.atomic():
            # Serialises concurrent syncs of the same account (idempotent task).
            SisAccount.objects.select_for_update().filter(pk=account.pk).first()
            courses = _CourseIndex(account.user_id)
            touched, cancelled = self._upsert_exams(account, exams, courses, counts)
            changed_schedules, new_schedules, gone = self._upsert_timetable(
                account, timetable, courses, counts
            )
            self._fill_tutors(timetable, courses)
            finished_at = self._now()
            account.status = SisAccount.Status.ACTIVE
            account.last_synced_at = finished_at
            account.last_sync_error = ""
            account.save(
                update_fields=["status", "last_synced_at", "last_sync_error", "updated_at"]
            )
            SisSyncLog.objects.create(
                sis_account=account,
                started_at=started_at,
                finished_at=finished_at,
                status=SisSyncLog.Status.SUCCESS,
                items_created=counts.created,
                items_updated=counts.updated,
                items_removed=counts.removed,
            )
        for item in touched:
            self._scheduler.schedule_for_item(item)
        for item in cancelled:
            self._scheduler.cancel_for_item(item)
        for schedule in gone:
            remove_lecture_schedule(schedule)
        for schedule in changed_schedules:
            regenerate_lecture_schedule(schedule, scheduler=self._scheduler)
        for schedule in new_schedules:
            expand_lecture_schedule(schedule, scheduler=self._scheduler)
        return SisSyncResult(
            status="success",
            items_created=counts.created,
            items_updated=counts.updated,
            items_removed=counts.removed,
        )

    def _upsert_exams(
        self,
        account: SisAccount,
        exams: list[ExamData],
        courses: _CourseIndex,
        counts: _Counts,
    ) -> tuple[list[Item], list[Item]]:
        existing = {
            item.external_id: item
            for item in Item.objects.select_for_update().filter(
                user_id=account.user_id, source=ItemSource.SIS, type=ItemType.EXAM
            )
        }
        touched: list[Item] = []
        for data in exams:
            enrollment = courses.find(data.course_code)
            values: dict[str, Any] = {
                "course_id": enrollment.course_id if enrollment else None,
                "title": data.title,
                "location": data.location,
                "scheduled_at": data.scheduled_at,
                "ends_at": data.ends_at,
            }
            item = existing.get(data.external_id)
            if item is None:
                item = Item.objects.create(
                    user_id=account.user_id,
                    type=ItemType.EXAM,
                    source=ItemSource.SIS,
                    external_id=data.external_id,
                    **values,
                )
                counts.created += 1
                touched.append(item)
                continue
            changed = [name for name in _EXAM_FIELDS if getattr(item, name) != values[name]]
            revived = item.deleted_at is not None
            if not changed and not revived:
                continue
            for name in changed:
                setattr(item, name, values[name])
            item.deleted_at = None
            item.save()
            counts.updated += 1
            touched.append(item)

        now = self._now()
        seen = {d.external_id for d in exams}
        removed = [
            item
            for item in existing.values()
            if item.external_id not in seen
            and item.deleted_at is None
            and (item.scheduled_at is None or item.scheduled_at >= now)
        ]
        for item in removed:
            item.deleted_at = now
            item.save(update_fields=["deleted_at", "updated_at"])
        counts.removed += len(removed)
        return touched, removed

    def _upsert_timetable(
        self,
        account: SisAccount,
        timetable: list[TimetableData],
        courses: _CourseIndex,
        counts: _Counts,
    ) -> tuple[list[LectureSchedule], list[LectureSchedule], list[LectureSchedule]]:
        existing = {
            schedule.external_id: schedule
            for schedule in LectureSchedule.objects.select_for_update().filter(
                user_id=account.user_id, source=ItemSource.SIS
            )
        }
        zone_name = str(_local_zone())
        changed_schedules: list[LectureSchedule] = []
        new_schedules: list[LectureSchedule] = []
        for data in timetable:
            enrollment = courses.find(data.course_code)
            values: dict[str, Any] = {
                "course_id": enrollment.course_id if enrollment else None,
                "title": data.course_code[:255],
                "weekdays": [data.weekday],
                "start_time": data.start_time,
                "duration_minutes": data.duration_minutes,
                "location": data.location,
                "starts_on": data.starts_on,
                "ends_on": data.ends_on,
            }
            schedule = existing.get(data.external_id)
            if schedule is None:
                new_schedules.append(
                    LectureSchedule.objects.create(
                        user_id=account.user_id,
                        source=ItemSource.SIS,
                        external_id=data.external_id,
                        timezone=zone_name,
                        **values,
                    )
                )
                counts.created += 1
                continue
            changed = [name for name in _SCHEDULE_FIELDS if getattr(schedule, name) != values[name]]
            if not changed:
                continue
            for name in changed:
                setattr(schedule, name, values[name])
            schedule.save()
            changed_schedules.append(schedule)
            counts.updated += 1

        seen = {d.external_id for d in timetable}
        gone = [s for key, s in existing.items() if key not in seen]
        counts.removed += len(gone)
        return changed_schedules, new_schedules, gone

    @staticmethod
    def _fill_tutors(timetable: list[TimetableData], courses: _CourseIndex) -> None:
        """Only fills an empty tutor: the Moodle sync (group members) wins."""
        for data in timetable:
            if not data.lecturer:
                continue
            enrollment = courses.find(data.course_code)
            if enrollment is None or enrollment.tutor_name:
                continue
            enrollment.tutor_name = data.lecturer
            enrollment.save(update_fields=["tutor_name", "updated_at"])

    def _mark_invalid(self, account: SisAccount) -> None:
        with transaction.atomic():
            locked = SisAccount.objects.select_for_update().get(pk=account.pk)
            if locked.status == SisAccount.Status.INVALID_CREDENTIALS:
                return  # already handled: notify only once
            locked.status = SisAccount.Status.INVALID_CREDENTIALS
            locked.last_sync_error = INVALID_CREDENTIALS_ERROR
            locked.save(update_fields=["status", "last_sync_error", "updated_at"])
        account.refresh_from_db()
        user = account.user
        message = Message(
            title=render_in(user.language, RECONNECT_TITLE),
            body=render_in(user.language, RECONNECT_BODY),
            data={"kind": "system", "route": "/sis"},
        )
        notify_user(user, message, kind=Notification.Kind.SYSTEM, channels=self._channels)

    def _log_failure(self, account: SisAccount, started_at: datetime, error: str) -> SisSyncResult:
        SisSyncLog.objects.create(
            sis_account=account,
            started_at=started_at,
            finished_at=self._now(),
            status=SisSyncLog.Status.FAILED,
            error=error,
        )
        return SisSyncResult(status="failed", error=error)
