"""Devices (FCM), Telegram links and the notification history."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, UUIDModel


class Channel(models.TextChoices):
    """Delivery channel codes. Each value matches the ``code`` of one channel
    registered in ``apps.notifications.channels.registry``."""

    PUSH = "push", _("Push")
    TELEGRAM = "telegram", _("Telegram")


class Device(UUIDModel, TimeStampedModel):
    class Platform(models.TextChoices):
        ANDROID = "android", _("Android")
        IOS = "ios", _("iOS")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    # Unique: a token moves to the latest user on re-login.
    fcm_token = models.TextField(_("FCM token"), unique=True)
    platform = models.CharField(_("platform"), max_length=16, choices=Platform.choices)
    app_version = models.CharField(_("app version"), max_length=32, blank=True)
    os_version = models.CharField(_("OS version"), max_length=32, blank=True)
    model = models.CharField(_("model"), max_length=128, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    last_seen_at = models.DateTimeField(_("last seen at"), null=True, blank=True)

    class Meta:
        db_table = "notifications_device"
        verbose_name = _("device")
        verbose_name_plural = _("devices")

    def __str__(self) -> str:
        return f"{self.platform}:{self.model or self.pk}"


class TelegramLink(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_link"
    )
    chat_id = models.BigIntegerField(_("chat id"), unique=True)
    username = models.CharField(_("username"), max_length=64, blank=True)
    linked_at = models.DateTimeField(_("linked at"))

    class Meta:
        db_table = "notifications_telegram_link"
        verbose_name = _("Telegram link")
        verbose_name_plural = _("Telegram links")

    def __str__(self) -> str:
        return self.username or str(self.chat_id)


class TelegramLinkToken(TimeStampedModel):
    """One-time deep-link token (10 min TTL, single use)."""

    token = models.CharField(_("token"), max_length=64, primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_link_tokens"
    )
    expires_at = models.DateTimeField(_("expires at"))
    used_at = models.DateTimeField(_("used at"), null=True, blank=True)

    class Meta:
        db_table = "notifications_telegram_link_token"
        verbose_name = _("Telegram link token")
        verbose_name_plural = _("Telegram link tokens")

    def __str__(self) -> str:
        return f"token:{self.user_id}"


class Notification(UUIDModel, TimeStampedModel):
    """History row shown in the app (one per delivered reminder/broadcast/reply)."""

    class Kind(models.TextChoices):
        REMINDER = "reminder", _("Reminder")
        BROADCAST = "broadcast", _("Broadcast")
        REPORT_REPLY = "report_reply", _("Report reply")
        SYSTEM = "system", _("System")
        ANNOUNCEMENT = "announcement", _("Announcement")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(_("kind"), max_length=16, choices=Kind.choices)
    title = models.CharField(_("title"), max_length=255)
    body = models.TextField(_("body"), blank=True)
    item = models.ForeignKey(
        "schedule.Item",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    report = models.ForeignKey(
        "support.Report",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    broadcast = models.ForeignKey(
        "broadcasts.Broadcast",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    class Meta:
        db_table = "notifications_notification"
        ordering = ("-created_at",)
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        indexes = [
            models.Index(fields=["user", "-created_at"], name="notification_user_created_idx"),
        ]

    def __str__(self) -> str:
        return self.title
