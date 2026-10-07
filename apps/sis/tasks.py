"""Celery tasks for the SIS sync. Thin and idempotent: load ids, call a service."""

from __future__ import annotations

from celery import shared_task
from django.conf import settings

from apps.sis.selectors import sis_account_by_id
from apps.sis.services.account import plan_sis_syncs


@shared_task(name="sis.sync_sis_account")
def sync_sis_account_task(sis_account_id: str) -> str:
    from config import container

    account = sis_account_by_id(sis_account_id)
    if account is None:
        return "missing"
    if not account.password_encrypted:
        return "no_password"  # device mode: the phone pushes the schedule instead
    return container.sync_sis_account()(account).status


@shared_task(name="sis.enqueue_sis_syncs")
def enqueue_sis_syncs() -> int:
    # Spread over most of the interval (6 hours by default) so syncs never pile up.
    spread = max(settings.SIS_SYNC_INTERVAL_MINUTES * 60 - 300, 0)
    planned = plan_sis_syncs(spread_seconds=spread)
    for plan in planned:
        sync_sis_account_task.apply_async(args=[str(plan.account_id)], countdown=plan.countdown)
    return len(planned)
