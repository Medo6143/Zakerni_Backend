"""Database side of a Moodle sync: upsert courses, enrollments and items, and soft-delete
items Moodle no longer reports. No Moodle calls and no scheduling side effects; those
belong to ``SyncMoodleAccount``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from apps.moodle.protocols import MoodleCourse
from apps.moodle.services.mappers import MoodleItemData
from apps.moodle.services.tutors import CourseTutor
from apps.schedule.models import Course, Enrollment, Item, ItemSource, ItemType

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


def upsert_courses(
    user_id: Any,
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
        if not created and (course.code != remote.code[:64] or course.name != remote.name[:255]):
            course.code = remote.code[:64]
            course.name = remote.name[:255]
            course.save(update_fields=["code", "name", "updated_at"])
        values: dict[str, Any] = {"is_active": True}
        tutor = tutors.get(remote.moodle_course_id)
        if tutor is not None:
            values["group_name"] = tutor.group_name
            values["tutor_name"] = tutor.tutor_name
        enrollment, created = Enrollment.objects.get_or_create(
            user_id=user_id, course=course, defaults=values
        )
        changed = [k for k, v in values.items() if getattr(enrollment, k) != v]
        if not created and changed:
            for name in changed:
                setattr(enrollment, name, values[name])
            enrollment.save(update_fields=[*changed, "updated_at"])
        mapping[remote.moodle_course_id] = course.id
    Enrollment.objects.filter(user_id=user_id, is_active=True).exclude(
        course_id__in=list(mapping.values())
    ).update(is_active=False, updated_at=timezone.now())
    return mapping


def upsert_items(
    user_id: Any,
    items: list[MoodleItemData],
    course_ids: dict[int, Any],
) -> tuple[int, int, list[Item]]:
    existing = {
        (item.type, item.external_id): item
        for item in Item.objects.select_for_update().filter(
            user_id=user_id, source=ItemSource.MOODLE
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
                user_id=user_id,
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


def remove_missing(
    user_id: Any, items: list[MoodleItemData], course_ids: dict[int, Any], now: datetime
) -> list[Item]:
    seen = {(d.type, d.external_id) for d in items}
    window_start = now - CALENDAR_PAST
    removed = [
        item
        for item in Item.objects.filter(
            user_id=user_id, source=ItemSource.MOODLE, deleted_at__isnull=True
        )
        if (item.type, item.external_id) not in seen
        and not _is_past_calendar_lecture(item, window_start, course_ids)
    ]
    for item in removed:
        item.deleted_at = now
        item.save(update_fields=["deleted_at", "updated_at"])
    return removed


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
