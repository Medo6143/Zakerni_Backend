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

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import SisInvalidCredentials, SisUnavailable
from apps.core.i18n import render_in
from apps.notifications.models import Notification
from apps.notifications.protocols import Message, NotificationChannel
from apps.notifications.services.history import notify_user
from apps.reminders.protocols import ReminderScheduler
from apps.schedule.services.lectures import (
    expand_lecture_schedule,
    regenerate_lecture_schedule,
    remove_lecture_schedule,
)
from apps.sis.models import SisAccount, SisSyncLog
from apps.sis.protocols import SisClient, SisScheduleEntry
from apps.sis.selectors import CourseIndex
from apps.sis.services.mappers import map_exams, map_timetable
from apps.sis.services.reconcile import (
    Counts,
    fill_tutors,
    local_zone,
    reconcile_exams,
    reconcile_timetable,
)

RECONNECT_TITLE = _("Reconnect the SIS")
RECONNECT_BODY = _(
    "Your SIS password no longer works. Reconnect it in Settings to keep your exams "
    "and lectures up to date."
)
INVALID_CREDENTIALS_ERROR = "invalid_credentials"


@dataclass(frozen=True)
class SisSyncResult:
    status: str  # "success" | "failed" | "skipped"
    items_created: int = 0
    items_updated: int = 0
    items_removed: int = 0
    error: str = ""


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
        exams = map_exams(entries, zone=local_zone(), language=language)
        timetable = map_timetable(entries, language=language)
        counts = Counts()
        with transaction.atomic():
            # Serialises concurrent syncs of the same account (idempotent task).
            SisAccount.objects.select_for_update().filter(pk=account.pk).first()
            courses = CourseIndex(account.user_id)
            touched, cancelled = reconcile_exams(
                account.user_id, self._now(), exams, courses, counts
            )
            changed_schedules, new_schedules, gone = reconcile_timetable(
                account.user_id, timetable, courses, counts
            )
            fill_tutors(timetable, courses)
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
