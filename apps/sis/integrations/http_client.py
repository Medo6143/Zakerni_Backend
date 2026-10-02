"""Concrete SIS client for the AOU Egypt student portal API (docs/01, "SIS integration").

The contract was discovered from the public web client bundle (no official docs):

- ``POST {base}/api/Student/GetStudentByCredentials`` ``{"Username", "Password"}`` ->
  a flat student object; valid when ``IsValid`` is true and ``Id`` is non-empty. It
  carries ``Token``, ``AcademicYear`` and ``AcademicSem``.
- ``GET {base}/api/StudentSchedule/GetStudentSchedules?sessionId=<Id>_<yyyyMMddHHmmssSSS>``
  with headers ``Authorization: <Token>`` (raw, no scheme) and ``stdtoken:
  base64(JSON {StudentId, AcademicYear, AcademicSem})`` -> a list of dated entries
  (``Event_Type`` "1" lecture, "2" exam, "3" university event).
- ``GET {base}/api/AcademicSession/GetCurrentWebRegistrationAcademicSessions`` -> the
  current academic year / semester (best effort: when it fails or has an unexpected
  shape, the year / semester returned by the login are used).

Everything is defensive: unknown or missing fields are skipped, and a response of an
unexpected shape is logged (no secrets, no personal data) and raised as
``SisUnavailable`` so the sync records an error instead of crashing.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import replace
from datetime import date, time
from http.cookies import CookieError, SimpleCookie
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from apps.core.exceptions import SisInvalidCredentials, SisUnavailable
from apps.sis.protocols import SisEntryKind, SisScheduleEntry, SisSession

logger = logging.getLogger(__name__)

LOGIN_PATH = "/api/Student/GetStudentByCredentials"
SCHEDULE_PATH = "/api/StudentSchedule/GetStudentSchedules"
CURRENT_SESSION_PATH = "/api/AcademicSession/GetCurrentWebRegistrationAcademicSessions"

_RETRIABLE_STATUS = {502, 503, 504}
_EVENT_KINDS: dict[str, SisEntryKind] = {"1": "lecture", "2": "exam"}
_ONLINE_WORDS = (
    "online",
    "teams",
    "zoom",
    "أونلاين",  # Arabic "online"
    "اونلاين",  # Arabic "online" (no hamza)
    "عن بعد",  # Arabic "remote"
)
_AM_MARKERS = {"a", "am", "ص"}
_PM_MARKERS = {"p", "pm", "م"}
_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})(?::(\d{2}))?\s*([AaPp][Mm]?|ص|م)?\s*$")


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int | float):
        return str(value)
    return ""


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1"}
    return False


def parse_time(value: Any) -> time | None:
    """``"13:30"``, ``"13:30:00"``, ``"1:30 PM"`` (also Arabic AM/PM markers) -> ``time``."""
    text = _text(value)
    if "T" in text:  # an ISO datetime
        text = text.split("T", 1)[1]
    match = _TIME_RE.match(text)
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    marker = (match.group(4) or "").lower()
    if marker in _PM_MARKERS and hour < 12:
        hour += 12
    elif marker in _AM_MARKERS and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def parse_date(value: Any) -> date | None:
    """``"2026-10-04"`` or ``"2026-10-04T00:00:00"`` -> ``date``."""
    text = _text(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_schedule_entry(raw: Any) -> SisScheduleEntry | None:
    """Map one ``GetStudentSchedules`` row; ``None`` for rows we cannot use."""
    if not isinstance(raw, dict):
        return None
    if "IsValid" in raw and not _truthy(raw.get("IsValid")):
        return None
    kind = _EVENT_KINDS.get(_text(raw.get("Event_Type")))
    day = parse_date(raw.get("date"))
    start = parse_time(raw.get("Start_Time"))
    code = _text(raw.get("Course_Part_Code"))
    if kind is None or day is None or start is None or not code:
        return None
    location_en = _text(raw.get("E_Location_Name"))
    location_ar = _text(raw.get("A_Location_Name"))
    link = _text(raw.get("Event_Link"))
    haystack = f"{location_en} {location_ar}".lower()
    return SisScheduleEntry(
        kind=kind,
        day=day,
        start_time=start,
        end_time=parse_time(raw.get("End_Time")),
        course_code=code[:64],
        location_en=location_en[:255],
        location_ar=location_ar[:255],
        lecturer_en=_text(raw.get("E_Lecturer_Name"))[:255],
        lecturer_ar=_text(raw.get("A_Lecturer_Name"))[:255],
        exam_name=_text(raw.get("Exam_Name"))[:128],
        is_online=bool(link) or any(word in haystack for word in _ONLINE_WORDS),
    )


def parse_schedule(data: Any) -> list[SisScheduleEntry]:
    if not isinstance(data, list):
        logger.warning("SIS schedule: unexpected response type %s", type(data).__name__)
        raise SisUnavailable(details={"sis_error": "unexpected_response"})
    entries = [parse_schedule_entry(row) for row in data]
    parsed = [e for e in entries if e is not None]
    skipped = len(entries) - len(parsed)
    if skipped:
        # Counts only: the rows hold personal data.
        logger.info("SIS schedule: skipped %d of %d rows", skipped, len(entries))
    return parsed


def _raw_scalar(value: Any) -> str | int:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int | str):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)  # the SIS sends 2026.0; its stdtoken check needs 2026
    return _text(value)


def parse_login(data: Any, cookies: tuple[tuple[str, str], ...] = ()) -> SisSession:
    if not isinstance(data, dict):
        logger.warning("SIS login: unexpected response type %s", type(data).__name__)
        raise SisUnavailable(details={"sis_error": "unexpected_response"})
    if not _truthy(data.get("IsValid")) or not _text(data.get("Id")):
        raise SisInvalidCredentials()
    token = _text(data.get("Token"))
    if not token:
        logger.warning("SIS login: valid response without a token")
        raise SisUnavailable(details={"sis_error": "unexpected_response"})
    return SisSession(
        student_id=_raw_scalar(data.get("Id")),
        token=token,
        academic_year=_raw_scalar(data.get("AcademicYear")),
        academic_sem=_raw_scalar(data.get("AcademicSem")),
        cookies=cookies,
    )


def parse_current_term(data: Any) -> tuple[str | int, str | int] | None:
    """``(AcademicYear, AcademicSem)`` of the current registration session, or ``None``."""
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if not isinstance(row, dict):
            continue
        year, sem = _raw_scalar(row.get("AcademicYear")), _raw_scalar(row.get("AcademicSem"))
        if year != "" and sem != "":
            return year, sem
    return None


def student_headers(session: SisSession) -> dict[str, str]:
    """Headers the web client's interceptor attaches to every signed-in call."""
    payload = json.dumps(
        {
            "StudentId": session.student_id,
            "AcademicYear": session.academic_year,
            "AcademicSem": session.academic_sem,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "Authorization": session.token,
        "stdtoken": base64.b64encode(payload.encode()).decode(),
    }


def _set_cookies(response: httpx.Response) -> tuple[tuple[str, str], ...]:
    jar = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        try:
            jar.load(header)
        except CookieError:
            continue
    return tuple((name, morsel.value) for name, morsel in jar.items())


class HttpSisClient:
    def __init__(
        self, base_url: str, timeout: float = 10.0, attempts: int = 3, proxy: str = ""
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._attempts = attempts
        self._proxy = proxy or None  # never logged: it may hold credentials

    @classmethod
    def from_settings(cls) -> HttpSisClient:
        return cls(
            base_url=settings.SIS_API_BASE_URL,
            timeout=settings.SIS_HTTP_TIMEOUT_SECONDS,
            proxy=settings.SIS_PROXY_URL,
        )

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self._base_url:
            raise SisUnavailable(details={"sis_error": "not_configured"})
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None
        for _attempt in range(self._attempts):
            try:
                if self._proxy:
                    kwargs["proxy"] = self._proxy
                response = httpx.request(method, url, timeout=self._timeout, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if response.status_code in _RETRIABLE_STATUS:
                last_exc = RuntimeError(f"SIS returned {response.status_code}")
                continue
            return response
        # Never include request data here: the login body holds the password.
        logger.warning("SIS %s %s failed after retries: %s", method, path, type(last_exc).__name__)
        raise SisUnavailable() from last_exc

    @staticmethod
    def _json(response: httpx.Response, path: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("SIS %s: response is not JSON (HTTP %s)", path, response.status_code)
            raise SisUnavailable(details={"sis_error": "unexpected_response"}) from exc

    def login(self, username: str, password: str) -> SisSession:
        response = self._send("POST", LOGIN_PATH, json={"Username": username, "Password": password})
        if response.status_code in {400, 401, 403}:
            raise SisInvalidCredentials()
        if response.status_code >= 400:
            raise SisUnavailable(details={"sis_error": f"http_{response.status_code}"})
        return parse_login(self._json(response, LOGIN_PATH), _set_cookies(response))

    def _with_current_term(self, session: SisSession) -> SisSession:
        """Align the ``stdtoken`` year / semester with the SIS' current session.

        Never fatal: the schedule call still works with the login's values."""
        try:
            response = self._send(
                "GET",
                CURRENT_SESSION_PATH,
                headers=student_headers(session),
                cookies=dict(session.cookies),
            )
            if response.status_code >= 400:
                return session
            term = parse_current_term(response.json())
        except (SisUnavailable, ValueError):
            return session
        if term is None:
            return session
        return replace(session, academic_year=term[0], academic_sem=term[1])

    def schedule(self, session: SisSession) -> list[SisScheduleEntry]:
        session = self._with_current_term(session)
        # The web client sends its own "session id": <student id>_<yyyyMMddHHmmssSSS>.
        stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")[:17]
        response = self._send(
            "GET",
            SCHEDULE_PATH,
            params={"sessionId": f"{session.student_id}_{stamp}"},
            headers=student_headers(session),
            cookies=dict(session.cookies),
        )
        if response.status_code >= 400:
            # Header names only (never values) so a rejected call can be diagnosed.
            logger.warning(
                "SIS schedule rejected: HTTP %s, sent cookies %s, www-authenticate %r",
                response.status_code,
                [name for name, _ in session.cookies],
                response.headers.get("www-authenticate", ""),
            )
            raise SisUnavailable(details={"sis_error": f"http_{response.status_code}"})
        return parse_schedule(self._json(response, SCHEDULE_PATH))
