"""Broadcast use cases: start from admin ("Send now"), deliver in each user's language."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.broadcasts.models import Broadcast
from apps.core.exceptions import ApplicationError
from apps.notifications.models import Notification
from apps.notifications.protocols import Message, NotificationChannel
from apps.notifications.selectors import notification_exists
from apps.notifications.services.history import deliver_to_user, record_notification


class BroadcastAlreadySent(ApplicationError):
    code = "broadcast_already_sent"
    status = 400
    message = _("This broadcast was already sent.")


def broadcast_audience(broadcast: Broadcast | None = None) -> Any:
    """Every active student account (staff excluded), or exactly the chosen
    recipient of a direct message (staff allowed when chosen explicitly)."""
    if broadcast is not None and broadcast.recipient_id is not None:
        return User.objects.filter(pk=broadcast.recipient_id, is_active=True)
    return User.objects.filter(is_active=True, is_staff=False)


def start_broadcast(broadcast: Broadcast, *, enqueue: Callable[[Any], None]) -> Broadcast:
    """Move a draft to ``sending`` and enqueue delivery. Idempotent per broadcast."""
    with transaction.atomic():
        locked = Broadcast.objects.select_for_update().get(pk=broadcast.pk)
        if locked.status != Broadcast.Status.DRAFT:
            raise BroadcastAlreadySent()
        locked.status = Broadcast.Status.SENDING
        locked.save(update_fields=["status", "updated_at"])
    transaction.on_commit(lambda: enqueue(locked.pk))
    return locked


def _message_for(broadcast: Broadcast, user: User) -> Message:
    return Message(
        title=broadcast.title_for(user.language),
        body=broadcast.body_for(user.language),
        data={"kind": "broadcast", "broadcast_id": str(broadcast.pk), "route": "/notifications"},
    )


def send_broadcast(broadcast: Broadcast, *, channels: Mapping[str, NotificationChannel]) -> int:
    """Deliver to every recipient once. Safe to re-run after a crash: users who
    already have a history row for this broadcast are skipped."""
    if broadcast.status == Broadcast.Status.SENT:
        return broadcast.recipients_count
    codes = broadcast.channel_codes
    recipients = 0
    for user in broadcast_audience(broadcast).iterator():
        if notification_exists(user=user, broadcast=broadcast):
            recipients += 1
            continue
        message = _message_for(broadcast, user)
        outcome = deliver_to_user(user, message, channels=channels, codes=codes)
        record_notification(
            user, kind=Notification.Kind.BROADCAST, message=message, broadcast=broadcast
        )
        if outcome.any_delivered:
            recipients += 1
    broadcast.status = Broadcast.Status.SENT
    broadcast.recipients_count = recipients
    broadcast.sent_at = timezone.now()
    broadcast.save(update_fields=["status", "recipients_count", "sent_at", "updated_at"])
    return recipients
