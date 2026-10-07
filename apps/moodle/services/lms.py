"""LMS status / manual sync request and the periodic sync planner."""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.core.exceptions import LmsTokenExpired, NotFoundAppError
from apps.moodle.models import MoodleAccount
from apps.moodle.selectors import active_moodle_account_ids, moodle_account_for_user

if TYPE_CHECKING:
    from apps.accounts.models import User

Enqueue = Callable[[uuid.UUID, int], None]  # (account_id, countdown_seconds)


def request_lms_sync(user: User, *, enqueue: Enqueue) -> MoodleAccount:
    """``POST /me/lms/sync``: enqueue an immediate sync of the user's account."""
    account = moodle_account_for_user(user.pk)
    if account is None:
        raise NotFoundAppError()
    if account.status == MoodleAccount.Status.EXPIRED:
        raise LmsTokenExpired()
    if account.status == MoodleAccount.Status.ACTIVE and account.has_token:
        enqueue(account.id, 0)
    return account


@dataclass(frozen=True)
class PlannedSync:
    account_id: uuid.UUID
    countdown: int


def plan_moodle_syncs(
    *, spread_seconds: int, rng: random.Random | None = None
) -> list[PlannedSync]:
    """One sync per active account, spread with countdown jitter over ``spread_seconds``."""
    rng = rng or random.Random()
    spread = max(spread_seconds, 0)
    return [
        PlannedSync(account_id=account_id, countdown=rng.randint(0, spread) if spread else 0)
        for account_id in active_moodle_account_ids()
    ]
