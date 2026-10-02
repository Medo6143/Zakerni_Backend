"""Recurring lecture schedules and their expansion into lecture ``Item`` rows.

On create/update every future occurrence from ``starts_on`` to ``ends_on`` is
generated at once (capped at ``MAX_SCHEDULE_DAYS`` ahead) and its reminders are
scheduled. ``expand_lecture_schedules`` runs daily and only fills gaps. The unique
``(lecture_schedule, scheduled_at)`` constraint makes expansion idempotent.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import ItemNotEditable, ValidationAppError
from apps.schedule.models import Course, Item, ItemSource, ItemType, LectureSchedule
from apps.schedule.selectors import active_lecture_schedules, is_enrolled

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.reminders.protocols import ReminderScheduler

MAX_SCHEDULE_DAYS = 366
MAX_DURATION_MINUTES = 600

_FIELDS = (
    "title",
    "weekdays",
    "start_time",
    "duration_minutes",
    "location",
    "starts_on",
    "ends_on",
)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(settings.DEFAULT_TIMEZONE)


def _validate(data: dict[str, Any]) -> None:
    errors: dict[str, list[str]] = {}
    weekdays = data["weekdays"]
    if (
        not weekdays
        or len(set(weekdays)) != len(weekdays)
        or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in weekdays)
    ):
        errors["weekdays"] = [str(_("Choose at least one day of the week."))]
    if data["ends_on"] < data["starts_on"]:
        errors["ends_on"] = [str(_("The end date must be on or after the start date."))]
    elif (data["ends_on"] - data["starts_on"]).days > MAX_SCHEDULE_DAYS:
        errors["ends_on"] = [str(_("A lecture schedule can span at most one year."))]
    if not 1 <= data["duration_minutes"] <= MAX_DURATION_MINUTES:
        errors["duration_minutes"] = [str(_("Duration must be between 1 and 600 minutes."))]
    if errors:
        raise ValidationAppError(details=errors)


def _resolve_course(user: User, course_id: uuid.UUID | None) -> Course | None:
    if course_id is None:
        return None
    if not is_enrolled(user, course_id):
        raise ValidationAppError(details={"course_id": [str(_("Unknown course."))]})
    return Course.objects.get(id=course_id)


def _occurrences(schedule: LectureSchedule, window_start: date, window_end: date) -> list[datetime]:
    zone = _zone(schedule.timezone)
    first = max(schedule.starts_on, window_start)
    last = min(schedule.ends_on, window_end)
    weekdays = set(schedule.weekdays)
    start_time: time = schedule.start_time
    result: list[datetime] = []
    day = first
    while day <= last:
        if day.weekday() in weekdays:
            local = datetime.combine(day, start_time, tzinfo=zone)
            result.append(local.astimezone(ZoneInfo("UTC")))
        day += timedelta(days=1)
    return result


def expand_lecture_schedule(
    schedule: LectureSchedule,
    *,
    scheduler: ReminderScheduler,
    today: date | None = None,
) -> int:
    """Create missing future occurrences up to ``ends_on`` (at most
    ``MAX_SCHEDULE_DAYS`` after ``today``).

    Returns the number of new items. Existing (including soft-deleted) occurrences
    are left alone.
    """
    zone = _zone(schedule.timezone)
    today = today or timezone.now().astimezone(zone).date()
    window_end = today + timedelta(days=MAX_SCHEDULE_DAYS)
    now = timezone.now()
    existing = set(
        Item.objects.filter(lecture_schedule=schedule).values_list("scheduled_at", flat=True)
    )
    created = 0
    for moment in _occurrences(schedule, today, window_end):
        if moment <= now or moment in existing:
            continue
        try:
            with transaction.atomic():
                item = Item.objects.create(
                    user_id=schedule.user_id,
                    course_id=schedule.course_id,
                    lecture_schedule=schedule,
                    type=ItemType.LECTURE,
                    source=schedule.source,
                    title=schedule.title,
                    location=schedule.location,
                    scheduled_at=moment,
                    ends_at=moment + timedelta(minutes=schedule.duration_minutes),
                )
        except IntegrityError:
            continue  # generated concurrently
        scheduler.schedule_for_item(item)
        created += 1
    return created


def _remove_future_items(schedule: LectureSchedule) -> int:
    """Future occurrences are deleted (their pending reminders cascade); past ones
    stay in history."""
    deleted, _unused = Item.objects.filter(
        lecture_schedule=schedule, scheduled_at__gt=timezone.now()
    ).delete()
    return deleted


def create_lecture_schedule(
    user: User,
    *,
    scheduler: ReminderScheduler,
    title: str,
    weekdays: list[int],
    start_time: time,
    duration_minutes: int,
    starts_on: date,
    ends_on: date,
    location: str = "",
    course_id: uuid.UUID | None = None,
) -> LectureSchedule:
    data = {
        "title": title,
        "weekdays": sorted(weekdays),
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "location": location,
        "starts_on": starts_on,
        "ends_on": ends_on,
    }
    _validate(data)
    course = _resolve_course(user, course_id)
    schedule = LectureSchedule.objects.create(
        user=user, course=course, timezone=user.timezone or settings.DEFAULT_TIMEZONE, **data
    )
    expand_lecture_schedule(schedule, scheduler=scheduler)
    return schedule


def update_lecture_schedule(
    schedule: LectureSchedule,
    *,
    scheduler: ReminderScheduler,
    **changes: Any,
) -> LectureSchedule:
    """Partial update; future occurrences are regenerated."""
    _ensure_editable(schedule)
    data = {name: getattr(schedule, name) for name in _FIELDS}
    for name in _FIELDS:
        if name in changes:
            data[name] = changes[name]
    data["weekdays"] = sorted(data["weekdays"])
    _validate(data)
    if "course_id" in changes:
        schedule.course = _resolve_course(schedule.user, changes["course_id"])
    for name, value in data.items():
        setattr(schedule, name, value)
    with transaction.atomic():
        schedule.save()
        _remove_future_items(schedule)
    expand_lecture_schedule(schedule, scheduler=scheduler)
    return schedule


def _ensure_editable(schedule: LectureSchedule) -> None:
    """SIS-imported timetables are managed by the SIS sync only."""
    if schedule.source != ItemSource.MANUAL:
        raise ItemNotEditable()


def regenerate_lecture_schedule(schedule: LectureSchedule, *, scheduler: ReminderScheduler) -> int:
    """Drop future occurrences and generate them again (after the schedule changed)."""
    _remove_future_items(schedule)
    return expand_lecture_schedule(schedule, scheduler=scheduler)


def delete_lecture_schedule(schedule: LectureSchedule) -> None:
    _ensure_editable(schedule)
    remove_lecture_schedule(schedule)


def remove_lecture_schedule(schedule: LectureSchedule) -> None:
    """Delete without the editability check (used by the SIS sync)."""
    with transaction.atomic():
        _remove_future_items(schedule)
        schedule.delete()  # past items keep their history (lecture_schedule -> NULL)


def expand_lecture_schedules(*, scheduler: ReminderScheduler, today: date | None = None) -> int:
    total = 0
    reference = today or timezone.now().date()
    for schedule in active_lecture_schedules(reference - timedelta(days=1)):
        total += expand_lecture_schedule(schedule, scheduler=scheduler, today=today)
    return total
