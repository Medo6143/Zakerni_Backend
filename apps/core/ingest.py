"""Result shared by the device-mode ingest use cases (Moodle and SIS)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class _SyncOutcome(Protocol):
    status: str
    items_created: int
    items_updated: int
    items_removed: int


@dataclass(frozen=True)
class IngestResult:
    status: str  # "success" | "failed"
    items_created: int
    items_updated: int
    items_removed: int
    last_synced_at: datetime | None

    @classmethod
    def from_sync(cls, result: _SyncOutcome, last_synced_at: datetime | None) -> IngestResult:
        return cls(
            status="success" if result.status == "success" else "failed",
            items_created=result.items_created,
            items_updated=result.items_updated,
            items_removed=result.items_removed,
            last_synced_at=last_synced_at,
        )
