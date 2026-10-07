"""App accounts: register, signin, change-password, admin temporary password."""

import pytest
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services.app_auth import (
    MAX_FAILED_ATTEMPTS,
    register_user,
    set_temporary_password,
)
from apps.accounts.tests.factories import UserFactory
from apps.reminders.models import ReminderRule

REGISTER = "/api/v1/auth/register"
SIGNIN = "/api/v1/auth/signin"
CHANGE = "/api/v1/auth/change-password"
GOOD = "correct-horse-42"

pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def no_throttle(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from rest_framework.throttling import ScopedRateThrottle

    rates = {**ScopedRateThrottle.THROTTLE_RATES, "login": "1000/min"}
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", rates)


def _register(client, **overrides):  # type: ignore[no-untyped-def]
    body = {"username": "2012345", "password": GOOD}
    body.update(overrides)
    return client.post(REGISTER, body, format="json")


def _signin(client, username="2012345", password="nope-nope-1"):  # type: ignore[no-untyped-def]
    return client.post(SIGNIN, {"username": username, "password": password}, format="json")


def test_register_success(client) -> None:
    response = _register(client, language="en")

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == {"access", "refresh", "user", "is_new"}
    assert payload["is_new"] is True
    assert payload["user"]["moodle_username"] == "2012345"
    assert payload["user"]["language"] == "en"
    user = User.objects.get(moodle_username="2012345")
    assert user.check_password(GOOD)
    assert GOOD not in user.password
    assert ReminderRule.objects.filter(user=user).exists()
    authed = APIClient()
    authed.credentials(HTTP_AUTHORIZATION=f"Bearer {payload['access']}")
    assert authed.get("/api/v1/me").status_code == 200


def test_register_normalizes_username(client) -> None:
    response = _register(client, username="  AbC123  ")

    assert response.status_code == 201
    assert response.json()["user"]["moodle_username"] == "abc123"
    assert _register(client, username="ABC123").status_code == 409


def test_register_duplicate_is_username_taken(client) -> None:
    assert _register(client).status_code == 201

    response = _register(client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "username_taken"


def test_register_legacy_unusable_password_account_is_username_taken(client) -> None:
    legacy = User(moodle_username="legacy1")
    legacy.set_unusable_password()
    legacy.save()

    response = _register(client, username="legacy1")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "username_taken"
    legacy.refresh_from_db()
    assert not legacy.has_usable_password()


@pytest.mark.parametrize("password", ["short1", "12345678901", "password", "2012345"])
def test_register_weak_password(client, password) -> None:
    response = _register(client, password=password)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "password" in error["details"]
    assert not User.objects.filter(moodle_username="2012345").exists()


@pytest.mark.parametrize("username", ["ab", "x" * 33, "has space", "a-b-c", "", "abc!"])
def test_register_invalid_username(client, username) -> None:
    response = _register(client, username=username)

    assert response.status_code == 400
    assert "username" in response.json()["error"]["details"]


def test_register_is_throttled(client) -> None:
    statuses = [_register(client, username=f"user{i}").status_code for i in range(6)]

    assert statuses[:5] == [201] * 5
    assert statuses[5] == 429


def test_signin_success(client) -> None:
    register_user(username="2012345", password=GOOD)

    response = _signin(client, " 2012345 ", GOOD)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"access", "refresh", "user", "is_new"}
    assert payload["is_new"] is False


def test_signin_failures_look_identical(client, no_throttle) -> None:
    register_user(username="2012345", password=GOOD)
    legacy = User(moodle_username="legacy1")
    legacy.set_unusable_password()
    legacy.save()

    wrong = _signin(client, "2012345")
    unknown = _signin(client, "999999")
    unusable = _signin(client, "legacy1")

    for response in (wrong, unknown, unusable):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json() == unknown.json() == unusable.json()


def test_signin_inactive_user_is_refused(client) -> None:
    user = register_user(username="2012345", password=GOOD)
    user.is_active = False
    user.save()

    assert _signin(client, "2012345", GOOD).status_code == 401


def test_signin_lockout_after_repeated_failures(client, no_throttle) -> None:
    register_user(username="2012345", password=GOOD)
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert _signin(client).status_code == 401

    locked = _signin(client)
    correct = _signin(client, "2012345", GOOD)

    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "too_many_attempts"
    assert correct.status_code == 429


def test_successful_signin_resets_failure_counter(client, no_throttle) -> None:
    register_user(username="2012345", password=GOOD)
    for _ in range(3):
        _signin(client)

    assert _signin(client, "2012345", GOOD).status_code == 200
    assert cache.get("signin-failures:2012345") is None


def test_signin_is_throttled(client) -> None:
    statuses = [_signin(client, "nobody", "x").status_code for _ in range(6)]

    assert statuses[5] == 429


def test_change_password_success_and_blacklists_old_refresh(client, no_throttle) -> None:
    register_user(username="2012345", password=GOOD)
    tokens = _signin(client, "2012345", GOOD).json()
    authed = APIClient()
    authed.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    response = authed.post(
        CHANGE, {"old_password": GOOD, "new_password": "another-pass-77"}, format="json"
    )

    assert response.status_code == 200
    assert set(response.json()) == {"access", "refresh"}
    assert User.objects.get(moodle_username="2012345").check_password("another-pass-77")
    refresh = "/api/v1/auth/refresh"
    old = client.post(refresh, {"refresh": tokens["refresh"]}, format="json")
    assert old.status_code == 400
    fresh = client.post(refresh, {"refresh": response.json()["refresh"]}, format="json")
    assert fresh.status_code == 200


def test_change_password_wrong_old_password(api, user) -> None:
    user.set_password(GOOD)
    user.save()

    response = api.post(
        CHANGE, {"old_password": "not-it-at-all", "new_password": "another-pass-77"}, format="json"
    )

    assert response.status_code == 400
    assert "old_password" in response.json()["error"]["details"]


def test_change_password_weak_new_password(api, user) -> None:
    user.set_password(GOOD)
    user.save()

    response = api.post(CHANGE, {"old_password": GOOD, "new_password": "12345678"}, format="json")

    assert response.status_code == 400
    assert "new_password" in response.json()["error"]["details"]
    user.refresh_from_db()
    assert user.check_password(GOOD)


def test_change_password_requires_auth(anon_api) -> None:
    response = anon_api.post(CHANGE, {"old_password": "a", "new_password": "b"}, format="json")

    assert response.status_code == 401


def test_error_messages_are_translated(client, no_throttle) -> None:
    register_user(username="2012345", password=GOOD)

    body = {"username": "2012345", "password": "nope-nope-1"}
    ar = client.post(SIGNIN, body, format="json", HTTP_ACCEPT_LANGUAGE="ar")
    en = client.post(SIGNIN, body, format="json", HTTP_ACCEPT_LANGUAGE="en")

    assert ar.json()["error"]["message"] != en.json()["error"]["message"]


def test_admin_set_temporary_password_action() -> None:
    admin_user = UserFactory(is_staff=True, is_superuser=True)
    student = UserFactory(password=make_password("old-password-1"))
    other = UserFactory(password=make_password("other-password-1"))
    web = Client()
    web.force_login(admin_user)

    response = web.post(
        "/admin/accounts/user/",
        {"action": "set_temporary_password", "_selected_action": [str(student.pk)]},
        follow=True,
    )

    assert response.status_code == 200
    student.refresh_from_db()
    other.refresh_from_db()
    assert not student.check_password("old-password-1")
    assert other.check_password("other-password-1")
    messages = [str(m) for m in response.context["messages"]]
    shown = next(m for m in messages if student.moodle_username in m)
    password = shown.split(": ", 1)[1].split(" (")[0]
    assert student.check_password(password)


def test_set_temporary_password_service_clears_lockout(client, no_throttle) -> None:
    user = register_user(username="2012345", password=GOOD)
    for _ in range(MAX_FAILED_ATTEMPTS):
        _signin(client)

    password = set_temporary_password(user)

    assert _signin(client, "2012345", password).status_code == 200


def test_admin_password_change_form_is_available() -> None:
    admin_user = UserFactory(is_staff=True, is_superuser=True)
    student = UserFactory()
    web = Client()
    web.force_login(admin_user)

    response = web.get(f"/admin/accounts/user/{student.pk}/password/")

    assert response.status_code == 200
