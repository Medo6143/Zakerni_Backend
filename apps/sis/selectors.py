from __future__ import annotations

import uuid
from typing import Any

from apps.sis.models import SisAccount

# Accounts the periodic sync picks up: a transient error must not stop syncing.
SYNCABLE_STATUSES = (SisAccount.Status.ACTIVE, SisAccount.Status.ERROR)


def sis_account_for_user(user_id: Any) -> SisAccount | None:
    return SisAccount.objects.filter(user_id=user_id).first()


def sis_account_by_id(account_id: Any) -> SisAccount | None:
    return SisAccount.objects.select_related("user").filter(id=account_id).first()


def syncable_sis_account_ids() -> list[uuid.UUID]:
    return list(
        SisAccount.objects.filter(status__in=SYNCABLE_STATUSES, user__is_active=True)
        .exclude(password_encrypted="")  # device mode: no password, nothing the server can fetch
        .values_list("id", flat=True)
    )
