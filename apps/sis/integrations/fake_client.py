"""In-memory fake SIS client for tests and local demos.

Fully interchangeable with ``HttpSisClient`` (Liskov Substitution): same protocol,
same exceptions, no network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.core.exceptions import SisInvalidCredentials, SisUnavailable
from apps.sis.protocols import SisScheduleEntry, SisSession


@dataclass
class FakeSisClient:
    valid_credentials: dict[str, str] = field(default_factory=dict)  # username -> password
    entries_by_user: dict[str, list[SisScheduleEntry]] = field(default_factory=dict)
    unavailable: bool = False
    logins: int = 0

    def add_user(
        self, username: str, password: str, entries: list[SisScheduleEntry] | None = None
    ) -> None:
        self.valid_credentials[username] = password
        self.entries_by_user[username] = list(entries or [])

    def login(self, username: str, password: str) -> SisSession:
        self.logins += 1
        if self.unavailable:
            raise SisUnavailable()
        if username not in self.valid_credentials or self.valid_credentials[username] != password:
            raise SisInvalidCredentials()
        return SisSession(student_id=username, token=f"tok-{username}", academic_year="2026")

    def schedule(self, session: SisSession) -> list[SisScheduleEntry]:
        if self.unavailable:
            raise SisUnavailable()
        return list(self.entries_by_user.get(str(session.student_id), []))
