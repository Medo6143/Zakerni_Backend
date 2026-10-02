"""Admin broadcasts: one message in both languages, each user gets their own."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, UUIDModel
from apps.notifications.models import Channel


class Broadcast(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SENDING = "sending", _("Sending")
        SENT = "sent", _("Sent")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="broadcasts",
    )
    title_ar = models.CharField(_("title (Arabic)"), max_length=255)
    body_ar = models.TextField(_("body (Arabic)"))
    title_en = models.CharField(_("title (English)"), max_length=255)
    body_en = models.TextField(_("body (English)"))
    send_push = models.BooleanField(_("send push"), default=True)
    send_telegram = models.BooleanField(_("send Telegram"), default=True)
    status = models.CharField(
        _("status"), max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    recipients_count = models.PositiveIntegerField(_("recipients"), default=0)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)

    class Meta:
        db_table = "broadcasts_broadcast"
        ordering = ("-created_at",)
        verbose_name = _("broadcast")
        verbose_name_plural = _("broadcasts")

    def __str__(self) -> str:
        return self.title_en or self.title_ar

    def title_for(self, language: str) -> str:
        return self.title_ar if language == "ar" else self.title_en

    def body_for(self, language: str) -> str:
        return self.body_ar if language == "ar" else self.body_en

    @property
    def channel_codes(self) -> set[str]:
        codes: set[str] = set()
        if self.send_push:
            codes.add(Channel.PUSH.value)
        if self.send_telegram:
            codes.add(Channel.TELEGRAM.value)
        return codes
