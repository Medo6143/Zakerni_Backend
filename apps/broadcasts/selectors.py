from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import Exists, OuterRef

from apps.accounts.models import User
from apps.broadcasts.models import Broadcast
from apps.notifications.models import Device, TelegramLink


def broadcast_by_id(broadcast_id: Any) -> Broadcast | None:
    return Broadcast.objects.filter(pk=broadcast_id).first()


def estimated_recipients(broadcast: Broadcast) -> int:
    """Preview: active students reachable through at least one selected channel."""
    from apps.broadcasts.services.send import broadcast_audience

    audience = broadcast_audience(broadcast)
    has_device = Exists(Device.objects.filter(user=OuterRef("pk"), is_active=True))
    has_telegram = Exists(TelegramLink.objects.filter(user=OuterRef("pk")))
    if broadcast.send_push and broadcast.send_telegram:
        return audience.filter(has_device | has_telegram).count()
    if broadcast.send_push:
        return audience.filter(has_device).count()
    if broadcast.send_telegram:
        return audience.filter(has_telegram).count()
    return 0


@dataclass(frozen=True)
class ChannelAvailability:
    active_devices: int
    telegram_linked: bool

    @property
    def any_available(self) -> bool:
        return self.active_devices > 0 or self.telegram_linked

    def reachable_through(self, *, push: bool, telegram: bool) -> tuple[int, bool]:
        """Of the selected channels: (devices that get a push, whether Telegram delivers)."""
        return (self.active_devices if push else 0, telegram and self.telegram_linked)


def channel_availability(user: User) -> ChannelAvailability:
    """Which channels can reach ``user`` right now."""
    return ChannelAvailability(
        active_devices=Device.objects.filter(user=user, is_active=True).count(),
        telegram_linked=TelegramLink.objects.filter(user=user).exists(),
    )
