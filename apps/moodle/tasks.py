"""Celery tasks for Moodle sync. Thin and idempotent: load ids, call a service."""

from __future__ import annotations

from celery import shared_task
from django.conf import settings

from apps.moodle.selectors import moodle_account_by_id
from apps.moodle.services.lms import plan_moodle_syncs


@shared_task(name="moodle.sync_moodle_account")
def sync_moodle_account_task(moodle_account_id: str) -> str:
    from config import container

    account = moodle_account_by_id(moodle_account_id)
    if account is None:
        return "missing"
    if not account.has_token:
        return "no_token"  # device mode: the phone pushes the data instead
    return container.sync_moodle_account()(account).status


@shared_task(name="moodle.enqueue_moodle_syncs")
def enqueue_moodle_syncs() -> int:
    # Spread over most of the interval so syncs never pile up on the next run.
    spread = max(settings.MOODLE_SYNC_INTERVAL_MINUTES * 60 - 300, 0)
    planned = plan_moodle_syncs(spread_seconds=spread)
    for plan in planned:
        sync_moodle_account_task.apply_async(args=[str(plan.account_id)], countdown=plan.countdown)
    return len(planned)
