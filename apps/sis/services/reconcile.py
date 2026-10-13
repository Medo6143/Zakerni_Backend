"""Reconcile SIS exams and weekly timetables with the student's stored rows.

Each function upserts what the SIS reports and soft-deletes (exams) or collects (timetables)
what it no longer reports. They only touch the database; scheduling side effects are
returned to the caller (``SyncSisAccount``) to run after the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

from apps.schedule.models import Item, ItemSource, ItemType, LectureSchedule
from apps.sis.selectors import CourseIndex
from apps.sis.services.mappers import ExamData, TimetableData

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


@dataclass
class Counts:
    created: int = 0
    updated: int = 0
    removed: int = 0


def local_zone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Africa/Cairo")


def reconcile_exams(
    user_id: Any,
    now: datetime,
    exams: list[ExamData],
    courses: CourseIndex,
    counts: Counts,
) -> tuple[list[Item], list[Item]]:
    existing = {
        item.external_id: item
        for item in Item.objects.select_for_update().filter(
            user_id=user_id, source=ItemSource.SIS, type=ItemType.EXAM
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
                user_id=user_id,
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


def reconcile_timetable(
    user_id: Any,
    timetable: list[TimetableData],
    courses: CourseIndex,
    counts: Counts,
) -> tuple[list[LectureSchedule], list[LectureSchedule], list[LectureSchedule]]:
    existing = {
        schedule.external_id: schedule
        for schedule in LectureSchedule.objects.select_for_update().filter(
            user_id=user_id, source=ItemSource.SIS
        )
    }
    zone_name = str(local_zone())
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
                    user_id=user_id,
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


def fill_tutors(timetable: list[TimetableData], courses: CourseIndex) -> None:
    """Only fills an empty tutor: the Moodle sync (group members) wins."""
    for data in timetable:
        if not data.lecturer:
            continue
        enrollment = courses.find(data.course_code)
        if enrollment is None or enrollment.tutor_name:
            continue
        enrollment.tutor_name = data.lecturer
        enrollment.save(update_fields=["tutor_name", "updated_at"])
