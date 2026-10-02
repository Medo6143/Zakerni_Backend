"""Daily cleanup (docs/01 section 3): old finished reminders."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.reminders.models import ScheduledReminder

_FINISHED = [
    ScheduledReminder.Status.SENT,
    ScheduledReminder.Status.FAILED,
    ScheduledReminder.Status.CANCELLED,
    ScheduledReminder.Status.SKIPPED,
]


def delete_old_reminders() -> int:
    cutoff = timezone.now() - timedelta(days=settings.REMINDER_HISTORY_RETENTION_DAYS)
    deleted, _unused = ScheduledReminder.objects.filter(
        status__in=_FINISHED, send_at__lt=cutoff
    ).delete()
    return deleted
