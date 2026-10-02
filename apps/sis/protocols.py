"""Ports for talking to the university Student Information System (SIS).

``SisAuthClient`` (sign in) and ``SisDataClient`` (schedule) are kept separate
(Interface Segregation). ``HttpSisClient`` implements both; tests use
``FakeSisClient``, which is fully interchangeable (Liskov Substitution).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Literal, Protocol

SisEntryKind = Literal["lecture", "exam"]


@dataclass(frozen=True)
class SisSession:
    """A short-lived signed-in SIS session. Never persisted."""

    # Kept exactly as the SIS returned them (number or string): the ``stdtoken`` header
    # must encode the same JSON values the web client sends.
    student_id: str | int
    token: str
    academic_year: str | int = ""
    academic_sem: str | int = ""
    # Cookies set by the login response; the web client sends them back on every call.
    cookies: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SisScheduleEntry:
    """One dated schedule entry (a lecture occurrence or an exam), in local SIS time."""

    kind: SisEntryKind
    day: date
    start_time: time
    end_time: time | None
    course_code: str
    location_en: str = ""
    location_ar: str = ""
    lecturer_en: str = ""
    lecturer_ar: str = ""
    exam_name: str = ""
    is_online: bool = False


class SisAuthClient(Protocol):
    def login(self, username: str, password: str) -> SisSession:
        """Raises ``SisInvalidCredentials`` or ``SisUnavailable``. Never logs the password."""
        ...


class SisDataClient(Protocol):
    def schedule(self, session: SisSession) -> list[SisScheduleEntry]:
        """Lectures and exams of the current academic session. Entries with missing
        or unparseable fields are skipped. Raises ``SisUnavailable`` (also for an
        unexpected response shape)."""
        ...


class SisClient(SisAuthClient, SisDataClient, Protocol):
    """Both ports; what the sync service needs."""
