"""``sync_moodle_account`` use case (docs/01 section 4.2).

1. courses -> upsert ``Course`` + ``Enrollment`` (with the student's group and tutor,
   best effort: see ``services/tutors.py``)
2. quizzes -> upsert ``Item(type=quiz)``; assignments -> upsert ``Item(type=tma)``;
   non-activity calendar events (e.g. Teams lectures) -> upsert ``Item(type=lecture)``
3. changed ``scheduled_at`` -> reschedule; items gone from Moodle -> soft delete + cancel
4. write a ``SyncLog``; on ``invalidtoken``: mark the account expired, send one
   "sign in again" notification and stop syncing it.

All Moodle calls happen before the database transaction, so a network failure
never leaves a half-applied sync.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import LmsTokenExpired, LmsUnavailable
from apps.core.i18n import render_in
from apps.moodle.models import MoodleAccount, SyncLog
from apps.moodle.protocols import MoodleCourse, MoodleDataClient
from apps.moodle.services.mappers import (
    MoodleItemData,
    map_assignment,
    map_calendar_event,
    map_quiz,
)
from apps.moodle.services.tutors import CourseTutor, fetch_course_tutor
from apps.notifications.models import Notification
from apps.notifications.protocols import Message, NotificationChannel
from apps.notifications.services.history import notify_user
from apps.reminders.protocols import ReminderScheduler
from apps.schedule.models import Course, Enrollment, Item, ItemSource, ItemType

TOKEN_EXPIRED_TITLE = _("Sign in again")
TOKEN_EXPIRED_BODY = _("Sign in again to keep your reminders working.")

_SYNCED_FIELDS = (
    "course_id",
    "title",
    "url",
    "available_from",
    "scheduled_at",
    "ends_at",
    "description",
)
# Calendar events (lectures) are fetched in this window around "now".
CALENDAR_PAST = timedelta(days=1)
CALENDAR_AHEAD = timedelta(days=60)


@dataclass(frozen=True)
class SyncResult:
    status: str  # "success" | "failed" | "skipped"
    items_created: int = 0
    items_updated: int = 0
    items_removed: int = 0
    error: str = ""


@dataclass(frozen=True)
class _Fetched:
    courses: list[MoodleCourse]
    items: list[MoodleItemData]
    tutors: dict[int, CourseTutor | None]


def _from_earlier_term(item: MoodleItemData, course_starts: Mapping[int, int]) -> bool:
    """AOU reuses course shells across terms: an activity or event dated before its
    course's ``startdate`` belongs to an earlier term and is skipped (then removed by
    ``_remove_missing`` if it was synced before)."""
    start = course_starts.get(item.moodle_course_id) or 0
    moment = item.scheduled_at or item.available_from
    if not start or moment is None:
        return False
    return moment.timestamp() < start


class SyncMoodleAccount:
    def __init__(
        self,
        client: MoodleDataClient,
        scheduler: ReminderScheduler,
        channels: Mapping[str, NotificationChannel],
        now: Callable[[], datetime] = timezone.now,
    ) -> None:
        self._client = client
        self._scheduler = scheduler
        self._channels = channels
        self._now = now

    def __call__(self, account: MoodleAccount) -> SyncResult:
        if account.status != MoodleAccount.Status.ACTIVE:
            return SyncResult(status="skipped")

        started_at = self._now()
        try:
            fetched = self._fetch(account)
        except LmsTokenExpired:
            self._mark_expired(account)
            return self._log_failure(account, started_at, "invalidtoken")
        except LmsUnavailable as exc:
            error = str(exc.details.get("moodle_error") or "lms_unavailable")
            account.last_sync_error = error
            account.save(update_fields=["last_sync_error", "updated_at"])
            return self._log_failure(account, started_at, error)

        with transaction.atomic():
            course_ids = self._upsert_courses(account, fetched.courses, fetched.tutors)
            created, updated, touched = self._upsert_items(account, fetched.items, course_ids)
            removed = self._remove_missing(account, fetched.items, course_ids)
            finished_at = self._now()
            account.last_synced_at = finished_at
            account.last_sync_error = ""
            account.save(update_fields=["last_synced_at", "last_sync_error", "updated_at"])
            SyncLog.objects.create(
                moodle_account=account,
                started_at=started_at,
                finished_at=finished_at,
                status=SyncLog.Status.SUCCESS,
                items_created=created,
                items_updated=updated,
                items_removed=len(removed),
            )
        for item in touched:
            self._scheduler.schedule_for_item(item)
        for item in removed:
            self._scheduler.cancel_for_item(item)
        return SyncResult(
            status="success",
            items_created=created,
            items_updated=updated,
            items_removed=len(removed),
        )

    # --- steps ----------------------------------------------------------------------

    def _fetch(self, account: MoodleAccount) -> _Fetched:
        token = account.get_token()
        courses = self._client.courses(token, account.moodle_user_id)
        ids = [c.moodle_course_id for c in courses]
        items = [map_quiz(q) for q in self._client.quizzes(token, ids)]
        items += [map_assignment(a) for a in self._client.assignments(token, ids)]
        now = self._now()
        events = self._client.calendar_events(
            token,
            ids,
            int((now - CALENDAR_PAST).timestamp()),
            int((now + CALENDAR_AHEAD).timestamp()),
        )
        # Activity events (quiz/assign) are already covered above.
        items += [map_calendar_event(e) for e in events if not e.module_name]
        starts = {c.moodle_course_id: c.start_date for c in courses}
        items = [i for i in items if not _from_earlier_term(i, starts)]
        # Best effort: a failed lookup keeps the tutor blank and never fails the sync.
        tutors = {
            cid: fetch_course_tutor(self._client, token, cid, account.moodle_user_id) for cid in ids
        }
        return _Fetched(courses=courses, items=items, tutors=tutors)

    def _upsert_courses(
        self,
        account: MoodleAccount,
        courses: list[MoodleCourse],
        tutors: Mapping[int, CourseTutor | None],
    ) -> dict[int, Any]:
        """Returns ``moodle_course_id -> Course.id``."""
        mapping: dict[int, Any] = {}
        for remote in courses:
            course, created = Course.objects.get_or_create(
                moodle_course_id=remote.moodle_course_id,
                defaults={"code": remote.code[:64], "name": remote.name[:255]},
            )
            if not created and (
                course.code != remote.code[:64] or course.name != remote.name[:255]
            ):
                course.code = remote.code[:64]
                course.name = remote.name[:255]
                course.save(update_fields=["code", "name", "updated_at"])
            values: dict[str, Any] = {"is_active": True}
            tutor = tutors.get(remote.moodle_course_id)
            if tutor is not None:
                values["group_name"] = tutor.group_name
                values["tutor_name"] = tutor.tutor_name
            enrollment, created = Enrollment.objects.get_or_create(
                user_id=account.user_id, course=course, defaults=values
            )
            changed = [k for k, v in values.items() if getattr(enrollment, k) != v]
            if not created and changed:
                for name in changed:
                    setattr(enrollment, name, values[name])
                enrollment.save(update_fields=[*changed, "updated_at"])
            mapping[remote.moodle_course_id] = course.id
        Enrollment.objects.filter(user_id=account.user_id, is_active=True).exclude(
            course_id__in=list(mapping.values())
        ).update(is_active=False, updated_at=timezone.now())
        return mapping

    def _upsert_items(
        self,
        account: MoodleAccount,
        items: list[MoodleItemData],
        course_ids: dict[int, Any],
    ) -> tuple[int, int, list[Item]]:
        existing = {
            (item.type, item.external_id): item
            for item in Item.objects.select_for_update().filter(
                user_id=account.user_id, source=ItemSource.MOODLE
            )
        }
        created = updated = 0
        touched: list[Item] = []
        for data in items:
            values = {
                "course_id": course_ids.get(data.moodle_course_id),
                "title": data.title,
                "url": data.url,
                "available_from": data.available_from,
                "scheduled_at": data.scheduled_at,
                "ends_at": data.ends_at,
                "description": data.description,
            }
            item = existing.get((data.type, data.external_id))
            if item is None:
                item = Item.objects.create(
                    user_id=account.user_id,
                    type=data.type,
                    source=ItemSource.MOODLE,
                    external_id=data.external_id,
                    **values,
                )
                created += 1
                touched.append(item)
                continue
            changed = [name for name in _SYNCED_FIELDS if getattr(item, name) != values[name]]
            revived = item.deleted_at is not None
            if not changed and not revived:
                continue
            for name in changed:
                setattr(item, name, values[name])
            item.deleted_at = None
            item.save()
            updated += 1
            if revived or "scheduled_at" in changed or "course_id" in changed:
                touched.append(item)
        return created, updated, touched

    def _remove_missing(
        self, account: MoodleAccount, items: list[MoodleItemData], course_ids: dict[int, Any]
    ) -> list[Item]:
        seen = {(d.type, d.external_id) for d in items}
        now = self._now()
        window_start = now - CALENDAR_PAST
        removed = [
            item
            for item in Item.objects.filter(
                user_id=account.user_id, source=ItemSource.MOODLE, deleted_at__isnull=True
            )
            if (item.type, item.external_id) not in seen
            and not self._is_past_calendar_lecture(item, window_start, course_ids)
        ]
        for item in removed:
            item.deleted_at = now
            item.save(update_fields=["deleted_at", "updated_at"])
        return removed

    @staticmethod
    def _is_past_calendar_lecture(
        item: Item, window_start: datetime, course_ids: dict[int, Any]
    ) -> bool:
        """Lectures older than the calendar window are simply no longer fetched: keep
        them as history while their course is still current."""
        return (
            item.type == ItemType.LECTURE
            and item.scheduled_at is not None
            and item.scheduled_at < window_start
            and (item.course_id is None or item.course_id in course_ids.values())
        )

    def _mark_expired(self, account: MoodleAccount) -> None:
        with transaction.atomic():
            locked = MoodleAccount.objects.select_for_update().get(pk=account.pk)
            if locked.status != MoodleAccount.Status.ACTIVE:
                return  # already handled: notify only once
            locked.status = MoodleAccount.Status.EXPIRED
            locked.last_sync_error = "invalidtoken"
            locked.save(update_fields=["status", "last_sync_error", "updated_at"])
        account.refresh_from_db()
        user = account.user
        message = Message(
            title=render_in(user.language, TOKEN_EXPIRED_TITLE),
            body=render_in(user.language, TOKEN_EXPIRED_BODY),
            data={"kind": "system", "route": "/login"},
        )
        notify_user(user, message, kind=Notification.Kind.SYSTEM, channels=self._channels)

    def _log_failure(self, account: MoodleAccount, started_at: datetime, error: str) -> SyncResult:
        SyncLog.objects.create(
            moodle_account=account,
            started_at=started_at,
            finished_at=self._now(),
            status=SyncLog.Status.FAILED,
            error=error,
        )
        return SyncResult(status="failed", error=error)
