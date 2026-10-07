"""Connect / disconnect the SIS, manual sync request and the periodic sync planner."""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import NotFoundAppError, SisInvalidCredentials
from apps.reminders.protocols import ReminderScheduler
from apps.schedule.models import Item, ItemSource, LectureSchedule
from apps.schedule.services.lectures import remove_lecture_schedule
from apps.sis.models import SisAccount
from apps.sis.protocols import SisAuthClient
from apps.sis.selectors import SYNCABLE_STATUSES, sis_account_for_user, syncable_sis_account_ids

if TYPE_CHECKING:
    from apps.accounts.models import User

Enqueue = Callable[[uuid.UUID, int], None]  # (account_id, countdown_seconds)


def connect_sis_account(
    user: User,
    *,
    username: str,
    password: str,
    client: SisAuthClient,
    enqueue: Enqueue,
) -> SisAccount:
    """``POST /me/sis``: verify by signing in once; nothing is stored on failure.

    Raises ``SisInvalidCredentials`` / ``SisUnavailable``. The password is stored
    Fernet-encrypted only after a successful sign-in (CLAUDE.md rule 2).
    """
    username = username.strip()
    client.login(username, password)
    with transaction.atomic():
        account = SisAccount.objects.select_for_update().filter(user=user).first()
        if account is None:
            account = SisAccount(user=user)
        account.username = username
        account.set_password(password)
        account.status = SisAccount.Status.ACTIVE
        account.last_sync_error = ""
        account.save()
    enqueue(account.id, 0)
    return account


def disconnect_sis_account(user: User, *, scheduler: ReminderScheduler) -> None:
    """``DELETE /me/sis``: delete the account (and its password) and remove what it
    imported: future SIS exams are soft deleted with their reminders cancelled, SIS
    timetables are deleted with their future occurrences. Past rows stay as history."""
    account = sis_account_for_user(user.pk)
    if account is None:
        raise NotFoundAppError()
    now = timezone.now()
    with transaction.atomic():
        exams = list(
            Item.objects.filter(
                user=user,
                source=ItemSource.SIS,
                lecture_schedule__isnull=True,
                deleted_at__isnull=True,
                scheduled_at__gte=now,
            )
        )
        for item in exams:
            item.deleted_at = now
            item.save(update_fields=["deleted_at", "updated_at"])
        for schedule in LectureSchedule.objects.filter(user=user, source=ItemSource.SIS):
            remove_lecture_schedule(schedule)
        account.delete()
    for item in exams:
        scheduler.cancel_for_item(item)


def request_sis_sync(user: User, *, enqueue: Enqueue) -> SisAccount:
    """``POST /me/sis/sync``: enqueue an immediate sync."""
    account = sis_account_for_user(user.pk)
    if account is None:
        raise NotFoundAppError()
    if account.status == SisAccount.Status.INVALID_CREDENTIALS:
        raise SisInvalidCredentials()
    if account.status in SYNCABLE_STATUSES and account.password_encrypted:
        enqueue(account.id, 0)
    return account


@dataclass(frozen=True)
class PlannedSisSync:
    account_id: uuid.UUID
    countdown: int


def plan_sis_syncs(
    *, spread_seconds: int, rng: random.Random | None = None
) -> list[PlannedSisSync]:
    """One sync per syncable account, spread with countdown jitter over ``spread_seconds``."""
    rng = rng or random.Random()
    spread = max(spread_seconds, 0)
    return [
        PlannedSisSync(account_id=account_id, countdown=rng.randint(0, spread) if spread else 0)
        for account_id in syncable_sis_account_ids()
    ]
