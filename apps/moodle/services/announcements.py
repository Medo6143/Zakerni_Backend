"""``ingest_announcements`` use case: store the course announcements the phone posted and
notify about new recent ones.

Unlike the other ingest lists this is not a snapshot: posts are only upserted by
``(user, moodle_discussion_id)``, never removed because they are missing. Posts older than
``RETENTION`` are deleted. Announcements of courses the student is not actively enrolled
in are skipped.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.i18n import render_in
from apps.moodle.models import CourseAnnouncement
from apps.moodle.protocols import MoodleAnnouncement
from apps.moodle.services.mappers import find_teams_link, from_timestamp, html_to_text
from apps.notifications.models import Notification
from apps.notifications.protocols import Message, NotificationChannel
from apps.notifications.services.history import notify_user
from apps.schedule.models import Course, Enrollment

if TYPE_CHECKING:
    from apps.accounts.models import User

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=180)
NOTIFY_WINDOW = timedelta(days=3)
MAX_NOTIFICATIONS = 5
TITLE_MAX = 80
PUSH_BODY_MAX = 140
LONG_BODY_MAX = 1000

TITLE_FORMAT = _("%(course)s: %(subject)s")
MORE_TITLE = _("Course announcements")
MORE_BODY = _("%(count)d more announcements")

_BLOCK_BREAKS = re.compile(r"</(?:p|div|li|h[1-6]|tr)>|<br\s*/?>", re.IGNORECASE)
_UPDATED_FIELDS = (
    "course_id",
    "forum_id",
    "group_id",
    "subject",
    "body",
    "author_name",
    "pinned",
    "modified_at",
    "url",
    "teams_url",
)


def announcement_text(message: str) -> str:
    """Plain text of an announcement: tags stripped, entities decoded, whitespace
    collapsed, paragraph breaks kept as newlines."""
    return html_to_text(_BLOCK_BREAKS.sub("\n", message or ""))


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def ingest_announcements(
    user: User,
    announcements: Iterable[MoodleAnnouncement],
    *,
    channels: Mapping[str, NotificationChannel],
    now: datetime | None = None,
) -> int:
    """Upsert the posts, drop expired ones and notify about the new recent ones. Returns
    the number of announcements created."""
    now = now or timezone.now()
    cutoff = now - RETENTION
    CourseAnnouncement.objects.filter(user=user, posted_at__lt=cutoff).delete()

    courses: dict[int, Course] = {
        e.course.moodle_course_id: e.course
        for e in Enrollment.objects.filter(user=user, is_active=True).select_related("course")
        if e.course.moodle_course_id is not None
    }
    existing = {a.moodle_discussion_id: a for a in CourseAnnouncement.objects.filter(user=user)}
    created: list[CourseAnnouncement] = []
    for data in announcements:
        course = courses.get(data.moodle_course_id)
        posted_at = from_timestamp(data.time_created)
        modified_at = from_timestamp(data.time_modified) or posted_at
        if course is None or posted_at is None or modified_at is None or posted_at < cutoff:
            continue
        values: dict[str, Any] = {
            "course_id": course.id,
            "forum_id": data.forum_id,
            "group_id": data.group_id,
            "subject": data.subject[:255],
            "body": announcement_text(data.message),
            "author_name": data.author_name[:255],
            "pinned": data.pinned,
            "modified_at": modified_at,
            "url": data.url[:500],
            "teams_url": find_teams_link(data.message)[:500],
        }
        row = existing.get(data.discussion_id)
        if row is None:
            row = CourseAnnouncement.objects.create(
                user=user,
                moodle_discussion_id=data.discussion_id,
                posted_at=posted_at,
                **values,
            )
            existing[data.discussion_id] = row
            created.append(row)
            continue
        changed = [name for name in _UPDATED_FIELDS if getattr(row, name) != values[name]]
        if changed:
            for name in changed:
                setattr(row, name, values[name])
            row.save(update_fields=[*changed, "updated_at"])

    _notify_new(user, created, courses, channels=channels, now=now)
    return len(created)


def _notify_new(
    user: User,
    created: list[CourseAnnouncement],
    courses: Mapping[int, Course],
    *,
    channels: Mapping[str, NotificationChannel],
    now: datetime,
) -> None:
    fresh = sorted(
        (a for a in created if a.notified_at is None and a.modified_at >= now - NOTIFY_WINDOW),
        key=lambda a: a.posted_at,
    )
    if not fresh:
        return
    codes = {c.id: c.code for c in courses.values()}
    for row in fresh[:MAX_NOTIFICATIONS]:
        _send(
            user,
            _announcement_message(user, row, codes.get(row.course_id, "") if row.course_id else ""),
            channels,
        )
    rest = len(fresh) - MAX_NOTIFICATIONS
    if rest > 0:
        message = Message(
            title=render_in(user.language, MORE_TITLE),
            body=render_in(user.language, MORE_BODY, count=rest),
            data={"kind": "announcement"},
        )
        _send(user, message, channels)
    CourseAnnouncement.objects.filter(pk__in=[a.pk for a in fresh]).update(notified_at=now)


def _announcement_message(user: User, row: CourseAnnouncement, code: str) -> Message:
    title = render_in(user.language, TITLE_FORMAT, course=code, subject=row.subject)
    link = row.teams_url or row.url
    long_body = "\n\n".join(p for p in (_truncate(row.body, LONG_BODY_MAX), link) if p)
    return Message(
        title=_truncate(title, TITLE_MAX),
        body=_truncate(row.body.replace("\n", " "), PUSH_BODY_MAX),
        data={"kind": "announcement", "announcement_id": str(row.pk)},
        long_body=long_body,
    )


def _send(user: User, message: Message, channels: Mapping[str, NotificationChannel]) -> None:
    try:
        notify_user(user, message, kind=Notification.Kind.ANNOUNCEMENT, channels=channels)
    except Exception:  # delivery must never fail the ingest
        logger.exception("Announcement notification failed for user %s", user.pk)
