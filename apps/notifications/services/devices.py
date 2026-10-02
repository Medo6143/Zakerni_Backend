"""FCM device registration use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Device
from apps.notifications.selectors import user_has_active_device

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.reminders.protocols import ReminderScheduler


@dataclass(frozen=True)
class DeviceRegistration:
    device: Device
    created: bool


def register_device(
    user: User,
    *,
    fcm_token: str,
    platform: str,
    app_version: str = "",
    os_version: str = "",
    model: str = "",
    scheduler: ReminderScheduler,
) -> DeviceRegistration:
    """Upsert by ``fcm_token``. A token seen for another user moves to this user
    (re-login on a shared phone). When the user gains their first active device,
    upcoming reminders are rescheduled so the push channel is included."""
    had_active_device = user_has_active_device(user)
    with transaction.atomic():
        device, created = Device.objects.select_for_update().get_or_create(
            fcm_token=fcm_token,
            defaults={
                "user": user,
                "platform": platform,
                "app_version": app_version,
                "os_version": os_version,
                "model": model,
                "is_active": True,
                "last_seen_at": timezone.now(),
            },
        )
        if not created:
            # If the token belonged to another user, that user's pending push
            # reminders are skipped at dispatch time (channel unavailable).
            device.user = user
            device.platform = platform
            device.app_version = app_version
            device.os_version = os_version
            device.model = model
            device.is_active = True
            device.last_seen_at = timezone.now()
            device.save()

    if not had_active_device:
        scheduler.reschedule_for_user(user)
    return DeviceRegistration(device=device, created=created)


def deactivate_device(device: Device) -> None:
    if device.is_active:
        device.is_active = False
        device.save(update_fields=["is_active", "updated_at"])


def deactivate_device_token(user: User, fcm_token: str) -> bool:
    """Used by logout and ``DELETE /devices/{fcm_token}``. Only the owner can deactivate."""
    updated = Device.objects.filter(user=user, fcm_token=fcm_token, is_active=True).update(
        is_active=False, updated_at=timezone.now()
    )
    return updated > 0
