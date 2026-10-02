import pytest
from rest_framework.test import APIClient

from apps.moodle.integrations.fake_client import FakeMoodleClient
from apps.moodle.protocols import SiteInfo


@pytest.fixture(autouse=True)
def _patch_login_client(monkeypatch):
    client = FakeMoodleClient()
    client.add_user(
        "student1",
        "secret",
        site_info=SiteInfo(moodle_user_id=1, full_name="Student One", email="s1@example.com"),
        token="tok-1",
    )

    import apps.accounts.api.views as views_module

    monkeypatch.setattr(
        views_module,
        "_login_service",
        lambda: views_module.LoginWithLms(auth_client=client, data_client=client),
    )
    return client


@pytest.mark.django_db
def test_login_endpoint_returns_tokens() -> None:
    api = APIClient()
    response = api.post(
        "/api/v1/auth/login", {"username": "student1", "password": "secret"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert "access" in body and "refresh" in body
    assert body["is_new"] is True
    assert body["user"]["moodle_username"] == "student1"


@pytest.mark.django_db
def test_login_endpoint_wrong_password_returns_envelope() -> None:
    api = APIClient()
    response = api.post(
        "/api/v1/auth/login", {"username": "student1", "password": "wrong"}, format="json"
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_lms_credentials"


@pytest.mark.django_db
def test_me_requires_authentication() -> None:
    api = APIClient()
    response = api.get("/api/v1/me")

    assert response.status_code == 401
