"""Reminder configuration and the scheduled reminder queue."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, UUIDModel
from apps.notifications.models import Channel
from apps.schedule.models import ItemType


class ReminderRule(UUIDModel, TimeStampedModel):
    """Per-user, per-item-type reminder offsets and channels (always one per type)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reminder_rules"
    )
    item_type = models.CharField(_("item type"), max_length=16, choices=ItemType.choices)
    offsets_minutes = models.JSONField(_("offsets (minutes)"), default=list)
    push_enabled = models.BooleanField(_("push enabled"), default=True)
    telegram_enabled = models.BooleanField(_("Telegram enabled"), default=False)

    class Meta:
        db_table = "reminders_rule"
        ordering = ("item_type",)
        verbose_name = _("reminder rule")
        verbose_name_plural = _("reminder rules")
        constraints = [
            models.UniqueConstraint(fields=["user", "item_type"], name="reminder_rule_unique_type"),
            models.CheckConstraint(
                condition=Q(item_type__in=[c.value for c in ItemType]),
                name="reminder_rule_item_type_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.item_type}"

    @property
    def enabled_channels(self) -> set[str]:
        channels: set[str] = set()
        if self.push_enabled:
            channels.add(Channel.PUSH.value)
        if self.telegram_enabled:
            channels.add(Channel.TELEGRAM.value)
        return channels


class ItemReminderOverride(UUIDModel, TimeStampedModel):
    item = models.OneToOneField(
        "schedule.Item", on_delete=models.CASCADE, related_name="reminder_override"
    )
    offsets_minutes = models.JSONField(_("offsets (minutes)"), default=list)

    class Meta:
        db_table = "reminders_item_override"
        verbose_name = _("item reminder override")
        verbose_name_plural = _("item reminder overrides")

    def __str__(self) -> str:
        return f"override:{self.item_id}"


class ScheduledReminder(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")
        SKIPPED = "skipped", _("Skipped")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scheduled_reminders"
    )
    item = models.ForeignKey(
        "schedule.Item", on_delete=models.CASCADE, related_name="scheduled_reminders"
    )
    offset_minutes = models.PositiveIntegerField(_("offset (minutes)"))
    channel = models.CharField(_("channel"), max_length=16, choices=Channel.choices)
    send_at = models.DateTimeField(_("send at"))
    status = models.CharField(
        _("status"), max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveSmallIntegerField(_("attempts"), default=0)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    error = models.TextField(_("error"), blank=True)

    class Meta:
        db_table = "reminders_scheduled"
        ordering = ("send_at",)
        verbose_name = _("scheduled reminder")
        verbose_name_plural = _("scheduled reminders")
        constraints = [
            # Hard rule #7: a reminder is never duplicated.
            models.UniqueConstraint(
                fields=["item", "offset_minutes", "channel"],
                name="scheduled_reminder_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["send_at"],
                condition=Q(status="pending"),
                name="scheduled_reminder_pending_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item_id}:{self.offset_minutes}:{self.channel}"
