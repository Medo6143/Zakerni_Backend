"""``dispatch_due_reminders`` (docs/01 section 4.4).

Each due row is claimed in its own short transaction with
``select_for_update(skip_locked=True)`` and re-checked to still be ``pending``,
so two workers never send the same row (hard rule #7). Retryable failures go
back to ``pending`` with ``send_at += 2 min`` until 3 attempts; rows more than
30 minutes late are ``skipped``. A successful send writes one history row per
(item, offset), even when several channels deliver it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.protocols import DeliveryResult, Message, NotificationChannel
from apps.notifications.services.history import record_notification
from apps.reminders.models import ScheduledReminder
from apps.reminders.selectors import due_reminder_ids
from apps.reminders.services.messages import render_reminder_message

Status = ScheduledReminder.Status
logger = logging.getLogger(__name__)


@dataclass
class DispatchStats:
    sent: int = 0
    failed: int = 0
    retried: int = 0
    skipped: int = 0
    cancelled: int = 0


class DispatchDueReminders:
    def __init__(
        self,
        channels: Mapping[str, NotificationChannel],
        *,
        now: Callable[[], datetime] = timezone.now,
        batch_size: int | None = None,
        max_attempts: int | None = None,
        retry_delay: timedelta | None = None,
        skip_late_after: timedelta | None = None,
    ) -> None:
        self._channels = channels
        self._now = now
        self._batch_size = batch_size or settings.REMINDER_DISPATCH_BATCH_SIZE
        self._max_attempts = max_attempts or settings.REMINDER_MAX_ATTEMPTS
        self._retry_delay = retry_delay or timedelta(minutes=settings.REMINDER_RETRY_DELAY_MINUTES)
        self._skip_late_after = skip_late_after or timedelta(
            minutes=settings.REMINDER_SKIP_LATE_MINUTES
        )

    def __call__(self) -> DispatchStats:
        stats = DispatchStats()
        for reminder_id in due_reminder_ids(self._now(), self._batch_size):
            self._process(reminder_id, stats)
        return stats

    def _process(self, reminder_id: uuid.UUID, stats: DispatchStats) -> None:
        with transaction.atomic():
            row = (
                ScheduledReminder.objects.select_for_update(skip_locked=True, of=("self",))
                .select_related("item", "item__course", "user")
                .filter(id=reminder_id, status=Status.PENDING)
                .first()
            )
            if row is None:
                return  # claimed by another worker, or no longer pending
            now = self._now()
            if row.send_at > now:
                return  # rescheduled into the future since we listed it

            item = row.item
            if (
                item.deleted_at is not None
                or item.is_muted
                or item.scheduled_at is None
                or not row.user.is_active
            ):
                self._finish(row, Status.CANCELLED, error="item_not_schedulable")
                stats.cancelled += 1
                return

            if now - row.send_at > self._skip_late_after:
                self._finish(row, Status.SKIPPED, error="late")
                stats.skipped += 1
                return

            channel = self._channels.get(row.channel)
            if channel is None or not channel.is_available_for(row.user):
                self._finish(row, Status.SKIPPED, error="channel_unavailable")
                stats.skipped += 1
                return

            message = render_reminder_message(item, user=row.user, now=now)
            try:
                result = channel.send(row.user, message)
            except Exception as exc:  # a misbehaving channel must not stop the whole batch
                logger.exception("reminder channel %s raised", row.channel)
                result = DeliveryResult(ok=False, retryable=True, error=f"channel_error: {exc}")
            row.attempts += 1

            if result.ok:
                row.status = Status.SENT
                row.sent_at = now
                row.error = ""
                row.save(update_fields=["status", "sent_at", "error", "attempts", "updated_at"])
                stats.sent += 1
                self._record_history(row, message)
            elif result.retryable and row.attempts < self._max_attempts:
                row.send_at = now + self._retry_delay
                row.error = result.error[:1000]
                row.save(update_fields=["send_at", "error", "attempts", "updated_at"])
                stats.retried += 1
            else:
                row.status = Status.FAILED
                row.error = result.error[:1000]
                row.save(update_fields=["status", "error", "attempts", "updated_at"])
                stats.failed += 1

    @staticmethod
    def _finish(row: ScheduledReminder, status: str, *, error: str) -> None:
        row.status = status
        row.error = error
        row.save(update_fields=["status", "error", "updated_at"])

    @staticmethod
    def _record_history(row: ScheduledReminder, message: Message) -> None:
        assert row.item.scheduled_at is not None
        # Sibling channel rows delivered for the current deadline (not an older one).
        due_moment = row.item.scheduled_at - timedelta(minutes=row.offset_minutes)
        already_delivered = (
            ScheduledReminder.objects.filter(
                item_id=row.item_id,
                offset_minutes=row.offset_minutes,
                status=Status.SENT,
                sent_at__gte=due_moment,
            )
            .exclude(id=row.id)
            .exists()
        )
        if not already_delivered:
            record_notification(
                row.user, kind=Notification.Kind.REMINDER, message=message, item=row.item
            )
