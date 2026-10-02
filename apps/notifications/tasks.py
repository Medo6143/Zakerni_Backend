"""Celery tasks for notifications. Thin and idempotent."""

from __future__ import annotations

from celery import shared_task

from apps.notifications.services.cleanup import delete_expired_link_tokens


@shared_task(name="notifications.cleanup_link_tokens")
def cleanup_link_tokens() -> int:
    return delete_expired_link_tokens()
