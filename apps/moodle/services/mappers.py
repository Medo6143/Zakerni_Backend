"""Map Moodle DTOs to ``Item`` field values (docs/01 section 4.2)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.utils.html import strip_tags

from apps.moodle.protocols import MoodleAssignment, MoodleCalendarEvent, MoodleQuiz
from apps.schedule.models import ItemType


@dataclass(frozen=True)
class MoodleItemData:
    type: str
    external_id: str
    moodle_course_id: int
    title: str
    url: str
    available_from: datetime | None
    scheduled_at: datetime | None
    ends_at: datetime | None = None
    description: str = ""


_TEAMS_LINK = re.compile(
    r"https://(?:[\w-]+\.)?teams\.(?:microsoft\.com|live\.com)/[^\s\"'<>]+", re.IGNORECASE
)


def from_timestamp(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def map_quiz(quiz: MoodleQuiz) -> MoodleItemData:
    """Quiz: ``available_from = timeopen``, ``scheduled_at = timeclose``."""
    return MoodleItemData(
        type=ItemType.QUIZ.value,
        external_id=str(quiz.instance_id),
        moodle_course_id=quiz.moodle_course_id,
        title=quiz.name[:255],
        url=quiz.url[:500],
        available_from=from_timestamp(quiz.time_open),
        scheduled_at=from_timestamp(quiz.time_close),
    )


def map_assignment(assignment: MoodleAssignment) -> MoodleItemData:
    """TMA: ``available_from = allowsubmissionsfromdate``, ``scheduled_at = duedate``."""
    return MoodleItemData(
        type=ItemType.TMA.value,
        external_id=str(assignment.instance_id),
        moodle_course_id=assignment.moodle_course_id,
        title=assignment.name[:255],
        url=assignment.url[:500],
        available_from=from_timestamp(assignment.allow_submissions_from),
        scheduled_at=from_timestamp(assignment.due_date),
    )


def find_teams_link(text: str) -> str:
    """First Microsoft Teams meeting link in ``text`` (HTML or plain), or ""."""
    match = _TEAMS_LINK.search(html.unescape(text or ""))
    return match.group(0) if match else ""


def html_to_text(value: str) -> str:
    text = html.unescape(strip_tags(value or ""))
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def map_calendar_event(event: MoodleCalendarEvent) -> MoodleItemData:
    """Calendar event -> lecture: ``scheduled_at = timestart``, ``ends_at = timestart +
    timeduration``, ``url`` = first Teams link in the description, else the event URL."""
    starts = from_timestamp(event.time_start)
    ends = (
        starts + timedelta(seconds=event.duration_seconds)
        if starts and event.duration_seconds > 0
        else None
    )
    return MoodleItemData(
        type=ItemType.LECTURE.value,
        external_id=f"event:{event.event_id}",
        moodle_course_id=event.moodle_course_id,
        title=event.name[:255],
        url=(find_teams_link(event.description) or event.url)[:500],
        available_from=None,
        scheduled_at=starts,
        ends_at=ends,
        description=html_to_text(event.description),
    )
