"""Parsing of recorded-shape SIS responses (built from the web client's models) and
the HTTP client's error mapping. The network is replaced by an in-process
``httpx`` transport stub; no request leaves the process."""

from __future__ import annotations

import base64
import json
from datetime import date, time
from pathlib import Path
from typing import Any

import httpx
import pytest

from apps.core.exceptions import SisInvalidCredentials, SisUnavailable
from apps.sis.integrations import http_client
from apps.sis.integrations.http_client import (
    HttpSisClient,
    parse_current_term,
    parse_login,
    parse_schedule,
    parse_time,
    student_headers,
)
from apps.sis.protocols import SisSession

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10:00", time(10, 0)),
        ("10:00:00", time(10, 0)),
        ("06:30 PM", time(18, 30)),
        ("12:15 am", time(0, 15)),
        ("01:30 م", time(13, 30)),
        ("2026-10-04T09:45:00", time(9, 45)),
        ("25:00", None),
        ("later", None),
        (None, None),
    ],
)
def test_parse_time(raw: Any, expected: time | None) -> None:
    assert parse_time(raw) == expected


def test_parse_login_fixture() -> None:
    session = parse_login(_fixture("login_response.json"))

    assert session == SisSession(
        student_id="2026123456",
        token="student-token-fixture",
        academic_year=2026,
        academic_sem=1,
    )


@pytest.mark.parametrize("body", [{"IsValid": False, "Id": None}, {"IsValid": True, "Id": ""}])
def test_parse_login_invalid(body: dict) -> None:
    with pytest.raises(SisInvalidCredentials):
        parse_login(body)


def test_parse_login_shape_mismatch() -> None:
    with pytest.raises(SisUnavailable) as exc:
        parse_login(["unexpected"])
    assert exc.value.details == {"sis_error": "unexpected_response"}
    with pytest.raises(SisUnavailable):
        parse_login({"IsValid": True, "Id": "1"})  # no token


def test_parse_schedule_fixture_skips_unusable_rows() -> None:
    entries = parse_schedule(_fixture("schedule_response.json"))

    assert [(e.kind, e.course_code, e.day) for e in entries] == [
        ("lecture", "M110", date(2026, 10, 4)),
        ("lecture", "M110", date(2026, 10, 11)),
        ("lecture", "TM112", date(2026, 10, 6)),
        ("exam", "M110", date(2026, 12, 20)),
    ]
    first, _second, online, exam = entries
    assert first.start_time == time(10, 0)
    assert first.end_time == time(12, 0)
    assert first.location_en == "Room 101"
    assert first.lecturer_en == "Dr. Tutor"
    assert first.is_online is False
    assert online.start_time == time(18, 30)
    assert online.is_online is True
    assert exam.exam_name == "Final"
    assert exam.location_en == "Hall A"


def test_parse_schedule_shape_mismatch() -> None:
    with pytest.raises(SisUnavailable) as exc:
        parse_schedule({"IsValid": False})
    assert exc.value.details == {"sis_error": "unexpected_response"}


def test_invalid_first_row_means_no_data() -> None:
    assert parse_schedule([{"IsValid": False}]) == []


def test_student_headers() -> None:
    headers = student_headers(SisSession("7", "tok", "2026", "1"))

    assert headers["Authorization"] == "tok"
    decoded = json.loads(base64.b64decode(headers["stdtoken"]))
    assert decoded == {"StudentId": "7", "AcademicYear": "2026", "AcademicSem": "1"}


def test_student_headers_keep_numeric_values() -> None:
    session = parse_login(
        {"IsValid": True, "Id": "25510470", "Token": "tok", "AcademicYear": 2026, "AcademicSem": 1}
    )

    decoded = json.loads(base64.b64decode(student_headers(session)["stdtoken"]))
    assert decoded == {"StudentId": "25510470", "AcademicYear": 2026, "AcademicSem": 1}


def test_login_cookies_are_sent_with_the_schedule(monkeypatch) -> None:
    login = httpx.Response(
        200,
        json={"IsValid": True, "Id": "7", "Token": "tok"},
        headers={"set-cookie": "ASP.NET_SessionId=abc; Path=/"},
        request=httpx.Request("POST", "https://sis.example/api/Student/GetStudentByCredentials"),
    )
    stub = _Stub(login, httpx.Response(200, json=[]), httpx.Response(200, json=[]))
    monkeypatch.setattr(httpx, "request", stub)
    client = HttpSisClient("https://sis.example")

    client.schedule(client.login("u", "p"))

    assert [c["cookies"] for c in stub.calls[1:]] == [{"ASP.NET_SessionId": "abc"}] * 2


class _Stub:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def install(*responses: httpx.Response | Exception) -> _Stub:
        fake = _Stub(*responses)
        monkeypatch.setattr(http_client.httpx, "request", fake)
        return fake

    return install


def test_login_and_schedule_requests(stub) -> None:  # type: ignore[no-untyped-def]
    fake = stub(
        httpx.Response(200, json=_fixture("login_response.json")),
        httpx.Response(200, json=[{"AcademicYear": 2026, "AcademicSem": 2}]),
        httpx.Response(200, json=_fixture("schedule_response.json")),
    )
    client = HttpSisClient("https://sis.example/API/", timeout=10)

    session = client.login("2026123456", "secret")
    entries = client.schedule(session)

    assert len(entries) == 4
    login_call, term_call, schedule_call = fake.calls
    assert login_call["method"] == "POST"
    assert login_call["url"] == "https://sis.example/API/api/Student/GetStudentByCredentials"
    assert login_call["json"] == {"Username": "2026123456", "Password": "secret"}
    assert login_call["timeout"] == 10
    assert term_call["method"] == "GET"
    assert term_call["url"] == (
        "https://sis.example/API/api/AcademicSession/GetCurrentWebRegistrationAcademicSessions"
    )
    assert term_call["headers"]["Authorization"] == "student-token-fixture"
    stdtoken = json.loads(base64.b64decode(schedule_call["headers"]["stdtoken"]))
    assert (stdtoken["AcademicYear"], stdtoken["AcademicSem"]) == (2026, 2)
    assert schedule_call["url"] == "https://sis.example/API/api/StudentSchedule/GetStudentSchedules"
    assert schedule_call["params"]["sessionId"].startswith("2026123456_")
    assert schedule_call["headers"]["Authorization"] == "student-token-fixture"


def test_login_retries_transient_failures(stub) -> None:  # type: ignore[no-untyped-def]
    fake = stub(
        httpx.ConnectError("down"),
        httpx.Response(503),
        httpx.Response(200, json=_fixture("login_response.json")),
    )

    HttpSisClient("https://sis.example").login("u", "p")

    assert len(fake.calls) == 3


def test_login_gives_up_after_retries(stub) -> None:  # type: ignore[no-untyped-def]
    stub(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))

    with pytest.raises(SisUnavailable):
        HttpSisClient("https://sis.example").login("u", "p")


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, json={"IsValid": False}), SisInvalidCredentials),
        (httpx.Response(401), SisInvalidCredentials),
        (httpx.Response(500), SisUnavailable),
        (httpx.Response(200, text="<html>maintenance</html>"), SisUnavailable),
    ],
)
def test_login_error_mapping(stub, response, error) -> None:  # type: ignore[no-untyped-def]
    stub(response)

    with pytest.raises(error):
        HttpSisClient("https://sis.example").login("u", "p")


def test_schedule_http_error_is_unavailable(stub) -> None:  # type: ignore[no-untyped-def]
    stub(httpx.Response(200, json=[]), httpx.Response(401))

    with pytest.raises(SisUnavailable) as exc:
        HttpSisClient("https://sis.example").schedule(SisSession("1", "t"))
    assert exc.value.details == {"sis_error": "http_401"}


@pytest.mark.parametrize(
    "term_response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_schedule_falls_back_to_login_term(stub, term_response) -> None:  # type: ignore[no-untyped-def]
    fake = stub(term_response, httpx.Response(200, json=[]))
    session = SisSession("1", "t", academic_year=2026, academic_sem=1)

    HttpSisClient("https://sis.example", attempts=1).schedule(session)

    stdtoken = json.loads(base64.b64decode(fake.calls[-1]["headers"]["stdtoken"]))
    assert (stdtoken["AcademicYear"], stdtoken["AcademicSem"]) == (2026, 1)


def test_parse_current_term() -> None:
    assert parse_current_term({"AcademicYear": 2026, "AcademicSem": 1}) == (2026, 1)
    assert parse_current_term([{"x": 1}, {"AcademicYear": "2026", "AcademicSem": "2"}]) == (
        "2026",
        "2",
    )
    assert parse_current_term([]) is None


def test_not_configured() -> None:
    with pytest.raises(SisUnavailable) as exc:
        HttpSisClient("").login("u", "p")
    assert exc.value.details == {"sis_error": "not_configured"}


def test_parse_login_integral_floats_become_ints() -> None:
    session = parse_login(
        {"IsValid": True, "Id": "7", "Token": "t", "AcademicYear": 2026.0, "AcademicSem": 1.0}
    )
    assert (session.academic_year, session.academic_sem) == (2026, 1)
    assert isinstance(session.academic_year, int)
