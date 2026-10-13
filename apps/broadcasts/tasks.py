"""Celery tasks for broadcasts. Thin and idempotent."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from apps.broadcasts.selectors import broadcast_by_id
from apps.broadcasts.services.send import send_broadcast as send_broadcast_service


def enqueue_broadcast(broadcast_id: Any) -> None:
    """Queue the delivery task (the ``enqueue`` callable the broadcast services receive)."""
    send_broadcast.delay(str(broadcast_id))


@shared_task(name="broadcasts.send_broadcast")
def send_broadcast(broadcast_id: str) -> int:
    from config import container

    broadcast = broadcast_by_id(broadcast_id)
    if broadcast is None:
        return 0
    return send_broadcast_service(broadcast, channels=container.notification_channels())
