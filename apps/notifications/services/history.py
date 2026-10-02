"""Notification history and one-off (non-reminder) deliveries."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.protocols import Message, NotificationChannel

if TYPE_CHECKING:
    from apps.accounts.models import User


@dataclass(frozen=True)
class DeliveryOutcome:
    delivered: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def any_delivered(self) -> bool:
        return bool(self.delivered)


def record_notification(
    user: User,
    *,
    kind: str,
    message: Message,
    item: Any = None,
    report: Any = None,
    broadcast: Any = None,
) -> Notification:
    return Notification.objects.create(
        user=user,
        kind=kind,
        title=message.title[:255],
        body=message.body,
        item=item,
        report=report,
        broadcast=broadcast,
    )


def deliver_to_user(
    user: User,
    message: Message,
    *,
    channels: Mapping[str, NotificationChannel],
    codes: Iterable[str] | None = None,
) -> DeliveryOutcome:
    """Send ``message`` through every available channel (optionally restricted to ``codes``)."""
    wanted = set(codes) if codes is not None else set(channels)
    outcome = DeliveryOutcome()
    for code, channel in channels.items():
        if code not in wanted or not channel.is_available_for(user):
            continue
        result = channel.send(user, message)
        if result.ok:
            outcome.delivered.add(code)
        else:
            outcome.failed[code] = result.error
    return outcome


def notify_user(
    user: User,
    message: Message,
    *,
    kind: str,
    channels: Mapping[str, NotificationChannel],
    codes: Iterable[str] | None = None,
    item: Any = None,
    report: Any = None,
    broadcast: Any = None,
) -> DeliveryOutcome:
    """Deliver and always keep a history row, so the in-app list shows it even
    when no channel is connected."""
    outcome = deliver_to_user(user, message, channels=channels, codes=codes)
    record_notification(
        user, kind=kind, message=message, item=item, report=report, broadcast=broadcast
    )
    return outcome


def mark_notifications_read(user: User, ids: list[uuid.UUID] | None = None) -> int:
    """Mark the given notifications (or all when ``ids`` is empty/None) as read."""
    queryset = Notification.objects.filter(user=user, read_at__isnull=True)
    if ids:
        queryset = queryset.filter(id__in=ids)
    return queryset.update(read_at=timezone.now(), updated_at=timezone.now())
