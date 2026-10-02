"""Manual exam/quiz CRUD and item mute (Moodle items are read-only; lectures go
through ``services/lectures.py``). Every change reschedules reminders explicitly."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import ItemNotEditable, NotFoundAppError, ValidationAppError
from apps.schedule.models import (
    MANUAL_CREATE_TYPES,
    Course,
    Item,
    ItemSource,
    ItemStatus,
    ItemType,
)
from apps.schedule.selectors import is_enrolled

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.reminders.protocols import ReminderScheduler

_UNSET: Any = object()

NOTE_MAX_LENGTH = 2000


def _resolve_course(user: User, course_id: uuid.UUID | None) -> Course | None:
    if course_id is None:
        return None
    if not is_enrolled(user, course_id):
        raise ValidationAppError(details={"course_id": [str(_("Unknown course."))]})
    return Course.objects.get(id=course_id)


def _validate_times(
    scheduled_at: datetime, ends_at: datetime | None, available_from: datetime | None = None
) -> None:
    if ends_at is not None and ends_at <= scheduled_at:
        raise ValidationAppError(
            details={"ends_at": [str(_("The end time must be after the start time."))]}
        )
    if available_from is not None and available_from >= scheduled_at:
        raise ValidationAppError(
            details={"available_from": [str(_("The opening time must be before the close time."))]}
        )


def _ensure_editable(item: Item) -> None:
    if item.source == ItemSource.MOODLE:
        raise ItemNotEditable()
    if item.lecture_schedule_id is not None:
        raise ItemNotEditable(
            message=str(_("Lecture occurrences are changed from the lecture schedule."))
        )


def create_manual_item(
    user: User,
    *,
    title: str,
    scheduled_at: datetime,
    scheduler: ReminderScheduler,
    course_id: uuid.UUID | None = None,
    ends_at: datetime | None = None,
    location: str = "",
    description: str = "",
    type: str = ItemType.EXAM,  # noqa: A002 - mirrors the API field name
    available_from: datetime | None = None,
) -> Item:
    """Create a manual exam or quiz (quiz: ``scheduled_at`` = close time,
    optional ``available_from`` = opens at)."""
    if type not in MANUAL_CREATE_TYPES:
        raise ValidationAppError(details={"type": [str(_("This type cannot be added manually."))]})
    course = _resolve_course(user, course_id)
    _validate_times(scheduled_at, ends_at, available_from)
    item = Item.objects.create(
        user=user,
        course=course,
        type=type,
        available_from=available_from,
        source=ItemSource.MANUAL,
        title=title,
        scheduled_at=scheduled_at,
        ends_at=ends_at,
        location=location,
        description=description,
    )
    scheduler.schedule_for_item(item)
    return item


def update_manual_item(
    item: Item,
    *,
    scheduler: ReminderScheduler,
    title: str = _UNSET,
    scheduled_at: datetime = _UNSET,
    course_id: uuid.UUID | None = _UNSET,
    ends_at: datetime | None = _UNSET,
    location: str = _UNSET,
    description: str = _UNSET,
    available_from: datetime | None = _UNSET,
) -> Item:
    _ensure_editable(item)
    if course_id is not _UNSET:
        item.course = _resolve_course(item.user, course_id)
    for name, value in (
        ("title", title),
        ("scheduled_at", scheduled_at),
        ("ends_at", ends_at),
        ("location", location),
        ("description", description),
        ("available_from", available_from),
    ):
        if value is not _UNSET:
            setattr(item, name, value)
    assert item.scheduled_at is not None
    _validate_times(item.scheduled_at, item.ends_at, item.available_from)
    item.save()
    scheduler.schedule_for_item(item)
    return item


def delete_manual_item(item: Item, *, scheduler: ReminderScheduler) -> None:
    """Soft delete (``deleted_at``) and cancel pending reminders."""
    _ensure_editable(item)
    item.deleted_at = timezone.now()
    item.save(update_fields=["deleted_at", "updated_at"])
    scheduler.cancel_for_item(item)


def set_item_status_note(
    user: User,
    item_id: uuid.UUID,
    *,
    status: str | None = None,
    note: str | None = None,
) -> Item:
    """Set the student's personal status and/or note on any of their own non-deleted
    items (any type/source, including Moodle/SIS: it is a personal annotation, not an
    edit of LMS data). Updates only the provided fields. Never touches reminders."""
    item = Item.objects.filter(user=user, id=item_id, deleted_at__isnull=True).first()
    if item is None:
        raise NotFoundAppError()

    update_fields: list[str] = []
    if status is not None:
        if status != "" and status not in ItemStatus.values:
            raise ValidationAppError(details={"status": [str(_("Invalid status."))]})
        item.status = status
        update_fields.append("status")
    if note is not None:
        if len(note) > NOTE_MAX_LENGTH:
            raise ValidationAppError(details={"note": [str(_("The note is too long."))]})
        item.note = note
        update_fields.append("note")

    if update_fields:
        update_fields.append("updated_at")
        item.save(update_fields=update_fields)
    return item


def set_item_muted(item: Item, *, is_muted: bool, scheduler: ReminderScheduler) -> Item:
    """Any item (Moodle or manual) can be muted."""
    if item.is_muted != is_muted:
        item.is_muted = is_muted
        item.save(update_fields=["is_muted", "updated_at"])
    scheduler.schedule_for_item(item)
    return item
