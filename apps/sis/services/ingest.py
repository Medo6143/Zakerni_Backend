"""``ingest_sis_entries`` use case: the phone fetched the schedule, the server stores it.

The posted entries are wrapped in a ``PayloadSisClient`` and the unchanged
``SyncSisAccount`` runs over them. Nothing here calls the SIS and no SIS password is
stored (device mode). Off unless ``SIS_INGEST_ENABLED``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings

from apps.core.exceptions import NotFoundAppError
from apps.sis.integrations.payload_client import PayloadSisClient
from apps.sis.models import SisAccount
from apps.sis.protocols import SisClient, SisScheduleEntry
from apps.sis.selectors import sis_account_for_user

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.sis.services.sync import SyncSisAccount

SyncFactory = Callable[[SisClient], "SyncSisAccount"]


@dataclass(frozen=True)
class SisIngestResult:
    status: str  # "success" | "failed"
    items_created: int
    items_updated: int
    items_removed: int
    last_synced_at: datetime | None


def ingest_sis_entries(
    user: User, entries: tuple[SisScheduleEntry, ...], *, build_sync: SyncFactory
) -> SisIngestResult:
    if not settings.SIS_INGEST_ENABLED:
        raise NotFoundAppError()
    account = sis_account_for_user(user.pk)
    if account is None:
        account = SisAccount.objects.create(user=user, username="")
    elif account.status in (SisAccount.Status.INVALID_CREDENTIALS, SisAccount.Status.ERROR):
        # The phone just read the SIS successfully: what blocked the server no longer applies.
        account.status = SisAccount.Status.ACTIVE
        account.last_sync_error = ""
        account.save(update_fields=["status", "last_sync_error", "updated_at"])

    result = build_sync(PayloadSisClient(entries=entries))(account)
    account.refresh_from_db()
    return SisIngestResult(
        status="success" if result.status == "success" else "failed",
        items_created=result.items_created,
        items_updated=result.items_updated,
        items_removed=result.items_removed,
        last_synced_at=account.last_synced_at,
    )
