"""Celery tasks for the schedule app. Thin and idempotent."""

from __future__ import annotations

from celery import shared_task

from apps.schedule.services.lectures import expand_lecture_schedules as expand_all


@shared_task(name="schedule.expand_lecture_schedules")
def expand_lecture_schedules() -> int:
    from config import container

    return expand_all(scheduler=container.reminder_scheduler())
