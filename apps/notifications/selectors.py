"""Read-only queries for devices, Telegram links and notification history."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.utils import timezone

from apps.notifications.models import Device, Notification, TelegramLink, TelegramLinkToken

if TYPE_CHECKING:
    from apps.accounts.models import User


def active_devices_for_user(user: User) -> QuerySet[Device]:
    return Device.objects.filter(user=user, is_active=True).order_by("-last_seen_at")


def user_has_active_device(user: User) -> bool:
    return Device.objects.filter(user=user, is_active=True).exists()


def device_by_token(fcm_token: str) -> Device | None:
    return Device.objects.filter(fcm_token=fcm_token).first()


def telegram_link_for_user(user: User) -> TelegramLink | None:
    return TelegramLink.objects.filter(user=user).first()


def is_telegram_linked(user: User) -> bool:
    return TelegramLink.objects.filter(user=user).exists()


def telegram_link_token(token: str) -> TelegramLinkToken | None:
    return TelegramLinkToken.objects.select_related("user").filter(token=token).first()


def notifications_for_user(user: User) -> QuerySet[Notification]:
    return Notification.objects.filter(user=user)


def unread_notifications_count(user: User) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def notification_exists(**filters: object) -> bool:
    return Notification.objects.filter(**filters).exists()


def expired_link_tokens() -> QuerySet[TelegramLinkToken]:
    return TelegramLinkToken.objects.filter(expires_at__lt=timezone.now())


def active_devices_count() -> int:
    return Device.objects.filter(is_active=True).count()


def telegram_linked_users_count() -> int:
    return TelegramLink.objects.count()


def notification_ids_for_user(user: User, ids: list[uuid.UUID]) -> QuerySet[Notification]:
    return Notification.objects.filter(user=user, id__in=ids)
