"""``SisClient`` backed by a schedule the phone already fetched.

Nothing here talks to the SIS: ``login`` returns an empty session and ``schedule``
returns the posted entries, so the unchanged ``SyncSisAccount`` can run over them.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.sis.protocols import SisScheduleEntry, SisSession


@dataclass(frozen=True)
class PayloadSisClient:
    entries: tuple[SisScheduleEntry, ...] = ()

    def login(self, username: str, password: str) -> SisSession:
        return SisSession(student_id="", token="")

    def schedule(self, session: SisSession) -> list[SisScheduleEntry]:
        return list(self.entries)
