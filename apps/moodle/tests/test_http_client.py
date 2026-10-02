import httpx
import pytest

from apps.core.exceptions import InvalidLmsCredentials, LmsUnavailable
from apps.moodle.integrations.http_client import HttpMoodleClient


def _client() -> HttpMoodleClient:
    return HttpMoodleClient("https://lms.example", "moodle_mobile_app", timeout=1)


def _respond(monkeypatch, response: httpx.Response) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: response)


def test_non_json_token_response_is_lms_unavailable(monkeypatch) -> None:
    _respond(monkeypatch, httpx.Response(200, text="<html>blocked</html>"))

    with pytest.raises(LmsUnavailable) as exc:
        _client().get_token("u", "secret-password")

    assert exc.value.details == {"moodle_error": "non_json_response"}


def test_non_json_token_response_never_logs_the_password(monkeypatch, caplog) -> None:
    _respond(monkeypatch, httpx.Response(403, text="<html>blocked</html>"))

    with pytest.raises(LmsUnavailable):
        _client().get_token("u", "secret-password")

    assert "secret-password" not in caplog.text


def test_invalid_login_still_maps_to_invalid_credentials(monkeypatch) -> None:
    _respond(monkeypatch, httpx.Response(200, json={"errorcode": "invalidlogin"}))

    with pytest.raises(InvalidLmsCredentials):
        _client().get_token("u", "wrong")
