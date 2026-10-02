"""Support reports ("Report a problem") with attachments and a reply thread."""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, UUIDModel


def report_attachment_path(instance: ReportAttachment, filename: str) -> str:
    # Unguessable file names: the original name (which may contain personal data) is dropped.
    suffix = PurePosixPath(filename).suffix.lower()[:8]
    return f"reports/{instance.report_id}/{uuid.uuid4().hex}{suffix}"


class Report(UUIDModel, TimeStampedModel):
    class Category(models.TextChoices):
        REMINDER_NOT_RECEIVED = "reminder_not_received", _("Reminder not received")
        WRONG_DATE = "wrong_date", _("Wrong date or time")
        LOGIN = "login", _("Login problem")
        TELEGRAM = "telegram", _("Telegram problem")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        NEW = "new", _("New")
        IN_PROGRESS = "in_progress", _("In progress")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")

    # Nullable: account deletion anonymises reports instead of deleting them.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    category = models.CharField(_("category"), max_length=32, choices=Category.choices)
    description = models.TextField(_("description"))
    status = models.CharField(
        _("status"), max_length=16, choices=Status.choices, default=Status.NEW
    )
    device_info = models.JSONField(_("device info"), default=dict, blank=True)
    app_version = models.CharField(_("app version"), max_length=32, blank=True)

    class Meta:
        db_table = "support_report"
        ordering = ("-created_at",)
        verbose_name = _("report")
        verbose_name_plural = _("reports")
        indexes = [
            models.Index(fields=["status", "created_at"], name="report_status_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_category_display()} ({self.get_status_display()})"


class ReportAttachment(UUIDModel, TimeStampedModel):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="attachments")
    file = models.ImageField(_("file"), upload_to=report_attachment_path)

    class Meta:
        db_table = "support_report_attachment"
        ordering = ("created_at",)
        verbose_name = _("report attachment")
        verbose_name_plural = _("report attachments")

    def __str__(self) -> str:
        return self.file.name


class ReportReply(UUIDModel, TimeStampedModel):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_replies",
    )
    is_staff = models.BooleanField(_("staff reply"), default=False)
    body = models.TextField(_("body"))

    class Meta:
        db_table = "support_report_reply"
        ordering = ("created_at",)
        verbose_name = _("report reply")
        verbose_name_plural = _("report replies")

    def __str__(self) -> str:
        return self.body[:50]
