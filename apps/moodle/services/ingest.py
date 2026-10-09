"""``ingest_lms_data`` use case: the phone fetched the data from Moodle, the server only
stores it (device mode, docs/01 section 4.2).

The posted data is wrapped in a ``PayloadMoodleClient`` and the unchanged
``SyncMoodleAccount`` runs over it, so the earlier-term filter, soft deletes, reminder
scheduling and ``SyncLog`` behave exactly as with a server-side fetch. Nothing here
calls Moodle.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING

from apps.core.exceptions import NotFoundAppError
from apps.moodle.integrations.payload_client import PayloadMoodleClient
from apps.moodle.models import MoodleAccount
from apps.moodle.protocols import (
    MoodleAnnouncement,
    MoodleAssignment,
    MoodleCalendarEvent,
    MoodleCourse,
    MoodleCourseMember,
    MoodleDataClient,
    MoodleGroup,
    MoodleQuiz,
)
from apps.moodle.selectors import moodle_account_for_user
from apps.moodle.services.announcements import ingest_announcements
from apps.notifications.protocols import NotificationChannel
from apps.schedule.models import Course

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.moodle.services.sync import SyncMoodleAccount

SyncFactory = Callable[[MoodleDataClient], "SyncMoodleAccount"]


@dataclass(frozen=True)
class LmsIngestData:
    courses: tuple[MoodleCourse, ...] = ()
    quizzes: tuple[MoodleQuiz, ...] = ()
    assignments: tuple[MoodleAssignment, ...] = ()
    events: tuple[MoodleCalendarEvent, ...] = ()
    groups_by_course: dict[int, list[MoodleGroup]] = field(default_factory=dict)
    members_by_group: dict[int, list[MoodleCourseMember]] = field(default_factory=dict)
    # Not a snapshot: announcements are only upserted, never removed.
    announcements: tuple[MoodleAnnouncement, ...] = ()
    # False for an announcements-only request: the snapshot sync is skipped (an empty
    # snapshot would remove everything).
    snapshot: bool = True
    token_expired: bool = False


@dataclass(frozen=True)
class LmsIngestResult:
    status: str  # "success" | "failed"
    items_created: int
    items_updated: int
    items_removed: int
    last_synced_at: datetime | None


def _pin_known_courses(courses: tuple[MoodleCourse, ...]) -> tuple[MoodleCourse, ...]:
    """``Course`` rows are shared between students: a payload may create a missing course
    but never renames one that already exists."""
    known = {
        c.moodle_course_id: c
        for c in Course.objects.filter(moodle_course_id__in=[c.moodle_course_id for c in courses])
    }
    return tuple(
        replace(c, code=known[c.moodle_course_id].code, name=known[c.moodle_course_id].name)
        if c.moodle_course_id in known
        else c
        for c in courses
    )


def ingest_lms_data(
    user: User,
    data: LmsIngestData,
    *,
    build_sync: SyncFactory,
    channels: Mapping[str, NotificationChannel] | None = None,
) -> LmsIngestResult:
    account = moodle_account_for_user(user.pk)
    if account is None:
        raise NotFoundAppError()
    if not data.token_expired and account.status == MoodleAccount.Status.EXPIRED:
        # The phone just read Moodle successfully, so its token works again.
        account.status = MoodleAccount.Status.ACTIVE
        account.last_sync_error = ""
        account.save(update_fields=["status", "last_sync_error", "updated_at"])

    if not data.snapshot:
        ingest_announcements(user, data.announcements, channels=channels or {})
        return LmsIngestResult(
            status="success",
            items_created=0,
            items_updated=0,
            items_removed=0,
            last_synced_at=account.last_synced_at,
        )

    client = PayloadMoodleClient(
        courses_=_pin_known_courses(data.courses),
        quizzes_=data.quizzes,
        assignments_=data.assignments,
        events_=data.events,
        groups_by_course=data.groups_by_course,
        members_by_group=data.members_by_group,
        token_expired=data.token_expired,
    )
    result = build_sync(client)(account)
    if data.announcements and result.status == "success":
        ingest_announcements(user, data.announcements, channels=channels or {})
    account.refresh_from_db()
    return LmsIngestResult(
        status="success" if result.status == "success" else "failed",
        items_created=result.items_created,
        items_updated=result.items_updated,
        items_removed=result.items_removed,
        last_synced_at=account.last_synced_at,
    )
