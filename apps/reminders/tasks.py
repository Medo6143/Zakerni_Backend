"""Celery tasks for reminders. Thin and idempotent."""

from __future__ import annotations

from celery import shared_task

from apps.reminders.services.cleanup import delete_old_reminders


@shared_task(name="reminders.dispatch_due_reminders")
def dispatch_due_reminders() -> dict[str, int]:
    from config import container

    stats = container.dispatch_due_reminders()()
    return {
        "sent": stats.sent,
        "failed": stats.failed,
        "retried": stats.retried,
        "skipped": stats.skipped,
        "cancelled": stats.cancelled,
    }


@shared_task(name="reminders.cleanup")
def cleanup_reminders() -> int:
    return delete_old_reminders()
