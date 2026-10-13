"""``ingest_sis_entries`` use case: the phone fetched the schedule, the server stores it.

The posted entries are wrapped in a ``PayloadSisClient`` and the unchanged
``SyncSisAccount`` runs over them. Nothing here calls the SIS and no SIS password is
stored (device mode). The feature flag (``SIS_INGEST_ENABLED``) is checked by the endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from apps.core.ingest import IngestResult
from apps.sis.integrations.payload_client import PayloadSisClient
from apps.sis.models import SisAccount
from apps.sis.protocols import SisClient, SisScheduleEntry
from apps.sis.selectors import sis_account_for_user

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.sis.services.sync import SyncSisAccount

SyncFactory = Callable[[SisClient], "SyncSisAccount"]


SisIngestResult = IngestResult


def ingest_sis_entries(
    user: User, entries: tuple[SisScheduleEntry, ...], *, build_sync: SyncFactory
) -> SisIngestResult:
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
    return IngestResult.from_sync(result, account.last_synced_at)
