"""``schedule_reminders_for_item`` (docs/01 section 4.3).

::

    effective_offsets = override.offsets if override exists else rule(item.type).offsets
    channels          = rule(item.type).channels  intersect  channels the user has connected
    if item is muted / deleted, course muted, or item in the past: cancel all pending
    for each offset x channel: send_at = scheduled_at - offset; if send_at > now: upsert pending
    cancel pending rows no longer in the set

Rows are unique on ``(item, offset_minutes, channel)`` (hard rule #7). A row that
was already sent/failed/skipped is only re-armed when the item moved later so
that its new ``send_at`` is after the old one (a genuinely new reminder moment);
otherwise it is left untouched and never sent twice.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.notifications.protocols import NotificationChannel
from apps.reminders.models import ItemReminderOverride, ReminderRule, ScheduledReminder
from apps.reminders.services.rules import ensure_reminder_rules
from apps.schedule.models import Enrollment, Item

if TYPE_CHECKING:
    from apps.accounts.models import User

Status = ScheduledReminder.Status
_TERMINAL = {Status.SENT, Status.FAILED, Status.SKIPPED}


@dataclass(frozen=True)
class _UserContext:
    rules: dict[str, ReminderRule]
    available_channels: frozenset[str]
    muted_course_ids: frozenset[uuid.UUID]


class ReminderSchedulingService:
    """Default ``ReminderScheduler`` implementation."""

    def __init__(
        self,
        channels: Mapping[str, NotificationChannel],
        now: Callable[[], datetime] = timezone.now,
    ) -> None:
        self._channels = channels
        self._now = now

    # --- public API (ReminderScheduler protocol) ----------------------------------

    def schedule_for_item(self, item: Item) -> None:
        self._schedule(item, self._context_for(item.user), self._now())

    def cancel_for_item(self, item: Item) -> None:
        ScheduledReminder.objects.filter(item=item, status=Status.PENDING).update(
            status=Status.CANCELLED, updated_at=timezone.now()
        )

    def reschedule_for_user(
        self,
        user: User,
        *,
        item_type: str | None = None,
        course_id: uuid.UUID | None = None,
    ) -> int:
        now = self._now()
        context = self._context_for(user)
        items = Item.objects.filter(user=user, deleted_at__isnull=True).filter(scheduled_at__gt=now)
        if item_type is not None:
            items = items.filter(type=item_type)
        if course_id is not None:
            items = items.filter(course_id=course_id)
        count = 0
        for item in items.select_related("user"):
            self._schedule(item, context, now)
            count += 1
        # Items that are now in the past can still hold pending rows only if they are
        # already due; dispatch handles those (sends or skips as late).
        return count

    # --- internals -----------------------------------------------------------------

    def _context_for(self, user: User) -> _UserContext:
        ensure_reminder_rules(user)
        rules = {rule.item_type: rule for rule in ReminderRule.objects.filter(user=user)}
        available = frozenset(
            code for code, channel in self._channels.items() if channel.is_available_for(user)
        )
        muted = frozenset(
            Enrollment.objects.filter(user=user, is_muted=True).values_list("course_id", flat=True)
        )
        return _UserContext(rules=rules, available_channels=available, muted_course_ids=muted)

    def _is_schedulable(self, item: Item, context: _UserContext, now: datetime) -> bool:
        if item.deleted_at is not None or item.is_muted or item.scheduled_at is None:
            return False
        if item.scheduled_at <= now:
            return False
        if item.course_id is not None and item.course_id in context.muted_course_ids:
            return False
        return bool(item.user.is_active)

    def _desired(
        self, item: Item, context: _UserContext, now: datetime
    ) -> dict[tuple[int, str], datetime]:
        if not self._is_schedulable(item, context, now):
            return {}
        rule = context.rules.get(item.type)
        if rule is None:
            return {}
        override = ItemReminderOverride.objects.filter(item=item).first()
        offsets = list(override.offsets_minutes if override else rule.offsets_minutes)
        channels = sorted(rule.enabled_channels & context.available_channels)
        assert item.scheduled_at is not None
        desired: dict[tuple[int, str], datetime] = {}
        for offset in offsets:
            send_at = item.scheduled_at - timedelta(minutes=int(offset))
            if send_at <= now:
                continue
            for channel in channels:
                desired[(int(offset), channel)] = send_at
        return desired

    def _schedule(self, item: Item, context: _UserContext, now: datetime) -> None:
        desired = self._desired(item, context, now)
        with transaction.atomic():
            existing = {
                (row.offset_minutes, row.channel): row
                for row in ScheduledReminder.objects.select_for_update().filter(item=item)
            }
            for key, send_at in desired.items():
                row = existing.get(key)
                if row is None:
                    self._create(item, key, send_at)
                elif row.status == Status.PENDING:
                    if row.send_at != send_at:
                        row.send_at = send_at
                        row.attempts = 0
                        row.error = ""
                        row.save(update_fields=["send_at", "attempts", "error", "updated_at"])
                elif row.status == Status.CANCELLED or (
                    row.status in _TERMINAL and send_at > row.send_at
                ):
                    self._rearm(row, send_at)
            for key, row in existing.items():
                if key not in desired and row.status == Status.PENDING:
                    row.status = Status.CANCELLED
                    row.save(update_fields=["status", "updated_at"])

    @staticmethod
    def _create(item: Item, key: tuple[int, str], send_at: datetime) -> None:
        offset, channel = key
        try:
            with transaction.atomic():
                ScheduledReminder.objects.create(
                    user_id=item.user_id,
                    item=item,
                    offset_minutes=offset,
                    channel=channel,
                    send_at=send_at,
                    status=Status.PENDING,
                )
        except IntegrityError:
            # Created concurrently by another scheduler run; the unique constraint wins.
            pass

    @staticmethod
    def _rearm(row: ScheduledReminder, send_at: datetime) -> None:
        row.status = Status.PENDING
        row.send_at = send_at
        row.attempts = 0
        row.sent_at = None
        row.error = ""
        row.save(update_fields=["status", "send_at", "attempts", "sent_at", "error", "updated_at"])
