"""Pure mapping from SIS schedule entries to the data the sync upserts.

- exams -> one ``ExamData`` each (``Item(type=exam, source=sis)``)
- lecture occurrences -> grouped into weekly ``TimetableData`` rows by
  (course, weekday, start, end, room); each becomes a ``LectureSchedule(source=sis)``
  spanning the first to the last dated occurrence.

External ids are stable hashes of the natural key so re-syncs are idempotent.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from apps.sis.protocols import SisScheduleEntry

DEFAULT_LECTURE_MINUTES = 60
MAX_LECTURE_MINUTES = 600


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def _external_id(key: str) -> str:
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()


def _pick(language: str, english: str, arabic: str) -> str:
    return (english or arabic) if language == "en" else (arabic or english)


@dataclass(frozen=True)
class ExamData:
    external_id: str
    course_code: str
    title: str
    scheduled_at: datetime
    ends_at: datetime | None
    location: str


@dataclass(frozen=True)
class TimetableData:
    external_id: str
    course_code: str
    weekday: int
    start_time: time
    duration_minutes: int
    location: str
    starts_on: date
    ends_on: date
    lecturer: str
    is_online: bool


def _minutes_between(start: time, end: time | None) -> int:
    if end is None:
        return DEFAULT_LECTURE_MINUTES
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if minutes <= 0:
        return DEFAULT_LECTURE_MINUTES
    return min(minutes, MAX_LECTURE_MINUTES)


def map_exams(entries: list[SisScheduleEntry], *, zone: ZoneInfo, language: str) -> list[ExamData]:
    result: list[ExamData] = []
    seen: set[str] = set()
    for entry in sorted((e for e in entries if e.kind == "exam"), key=lambda e: e.day):
        code = normalize_code(entry.course_code)
        key = f"exam|{code}|{entry.exam_name.lower() or entry.day.isoformat()}"
        if key in seen:  # two exams with the same name: tell them apart by date
            key = f"{key}|{entry.day.isoformat()}|{entry.start_time.isoformat()}"
        if key in seen:
            continue
        seen.add(key)
        start = datetime.combine(entry.day, entry.start_time, tzinfo=zone)
        end = datetime.combine(entry.day, entry.end_time, tzinfo=zone) if entry.end_time else None
        if end is not None and end <= start:
            end = None
        title = f"{entry.course_code} - {entry.exam_name}" if entry.exam_name else entry.course_code
        result.append(
            ExamData(
                external_id=_external_id(key),
                course_code=entry.course_code,
                title=title[:255],
                scheduled_at=start.astimezone(ZoneInfo("UTC")),
                ends_at=end.astimezone(ZoneInfo("UTC")) if end else None,
                location=_pick(language, entry.location_en, entry.location_ar)[:255],
            )
        )
    return result


def map_timetable(entries: list[SisScheduleEntry], *, language: str) -> list[TimetableData]:
    groups: dict[str, list[SisScheduleEntry]] = {}
    for entry in entries:
        if entry.kind != "lecture":
            continue
        room = normalize_code(entry.location_en or entry.location_ar)
        end = entry.end_time.isoformat() if entry.end_time else ""
        key = (
            f"lecture|{normalize_code(entry.course_code)}|{entry.day.weekday()}"
            f"|{entry.start_time.isoformat()}|{end}|{room}"
        )
        groups.setdefault(key, []).append(entry)
    result: list[TimetableData] = []
    for key, rows in groups.items():
        first = rows[0]
        days = [r.day for r in rows]
        result.append(
            TimetableData(
                external_id=_external_id(key),
                course_code=first.course_code,
                weekday=first.day.weekday(),
                start_time=first.start_time,
                duration_minutes=_minutes_between(first.start_time, first.end_time),
                location=_pick(language, first.location_en, first.location_ar)[:255],
                starts_on=min(days),
                ends_on=max(days),
                lecturer=_pick(language, first.lecturer_en, first.lecturer_ar)[:255],
                is_online=any(r.is_online for r in rows),
            )
        )
    return sorted(result, key=lambda t: (t.starts_on, t.weekday, t.start_time))
