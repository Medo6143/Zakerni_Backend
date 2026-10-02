from __future__ import annotations

from typing import Any

from django.db.models import Exists, OuterRef

from apps.broadcasts.models import Broadcast
from apps.notifications.models import Device, TelegramLink


def broadcast_by_id(broadcast_id: Any) -> Broadcast | None:
    return Broadcast.objects.filter(pk=broadcast_id).first()


def estimated_recipients(broadcast: Broadcast) -> int:
    """Preview: active students reachable through at least one selected channel."""
    from apps.broadcasts.services.send import broadcast_audience

    audience = broadcast_audience()
    has_device = Exists(Device.objects.filter(user=OuterRef("pk"), is_active=True))
    has_telegram = Exists(TelegramLink.objects.filter(user=OuterRef("pk")))
    if broadcast.send_push and broadcast.send_telegram:
        return audience.filter(has_device | has_telegram).count()
    if broadcast.send_push:
        return audience.filter(has_device).count()
    if broadcast.send_telegram:
        return audience.filter(has_telegram).count()
    return 0
