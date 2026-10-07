import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services.device_auth import hash_device_secret, reset_device_binding
from apps.moodle.models import MoodleAccount
from apps.reminders.models import ReminderRule

URL = "/api/v1/auth/device-login"
SECRET = "a" * 40
OTHER_SECRET = "b" * 40


def body(**overrides) -> dict:  # type: ignore[no-untyped-def]
    data = {
        "username": "student9",
        "full_name": "Student Nine",
        "email": "s9@example.com",
        "moodle_user_id": 9,
        "site_url": "https://lms.example.edu",
        "device_secret": SECRET,
    }
    data.update(overrides)
    return data


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_first_claim_creates_user_account_and_rules(client, fake_clients) -> None:
    response = client.post(URL, body(), format="json")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"access", "refresh", "user", "is_new"}
    assert payload["is_new"] is True
    assert payload["user"]["moodle_username"] == "student9"
    user = User.objects.get(moodle_username="student9")
    assert user.device_secret_hash == hash_device_secret(SECRET)
    assert SECRET not in user.device_secret_hash
    assert user.device_bound_at is not None
    account = MoodleAccount.objects.get(user=user)
    assert account.token_encrypted == ""
    assert account.status == MoodleAccount.Status.ACTIVE
    assert (account.site_url, account.moodle_user_id) == ("https://lms.example.edu", 9)
    assert ReminderRule.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_same_secret_logs_in_again_and_updates_profile(client) -> None:
    client.post(URL, body(), format="json")

    response = client.post(URL, body(full_name="New Name", moodle_user_id=10), format="json")

    assert response.status_code == 200
    assert response.json()["is_new"] is False
    user = User.objects.get(moodle_username="student9")
    assert user.full_name == "New Name"
    assert MoodleAccount.objects.get(user=user).moodle_user_id == 10
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_issued_access_token_works(client) -> None:
    payload = client.post(URL, body(), format="json").json()
    token = payload["access"]

    me = APIClient()
    me.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert me.get("/api/v1/me").json()["moodle_username"] == "student9"


@pytest.mark.django_db
def test_wrong_secret_is_refused_with_device_mismatch(client) -> None:
    client.post(URL, body(), format="json")

    response = client.post(URL, body(device_secret=OTHER_SECRET), format="json")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "device_mismatch"
    assert User.objects.get(moodle_username="student9").device_secret_hash == (
        hash_device_secret(SECRET)
    )


@pytest.mark.django_db
def test_existing_unbound_user_is_claimed_by_first_device(client, user) -> None:
    response = client.post(URL, body(username=user.moodle_username), format="json")

    assert response.status_code == 200
    assert response.json()["is_new"] is False
    user.refresh_from_db()
    assert user.device_secret_hash == hash_device_secret(SECRET)


@pytest.mark.django_db
def test_token_of_an_older_login_is_dropped(client) -> None:
    client.post(URL, body(), format="json")
    user = User.objects.get(moodle_username="student9")
    account = MoodleAccount.objects.get(user=user)
    account.set_token("old-server-token")
    account.save()

    client.post(URL, body(), format="json")

    assert MoodleAccount.objects.get(user=user).token_encrypted == ""


@pytest.mark.django_db
def test_reset_device_binding_lets_a_new_device_claim(client) -> None:
    client.post(URL, body(), format="json")
    user = User.objects.get(moodle_username="student9")

    reset_device_binding(user)
    response = client.post(URL, body(device_secret=OTHER_SECRET), format="json")

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.device_secret_hash == hash_device_secret(OTHER_SECRET)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"device_secret": "short"},
        {"username": ""},
        {"moodle_user_id": 0},
        {"site_url": "not a url"},
        {"email": "nope"},
        {"username": "x" * 151},
    ],
)
def test_invalid_body_is_rejected(client, overrides) -> None:
    response = client.post(URL, body(**overrides), format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert not User.objects.filter(moodle_username="student9").exists()


@pytest.mark.django_db
def test_empty_email_is_allowed(client) -> None:
    assert client.post(URL, body(email=""), format="json").status_code == 200


@pytest.mark.django_db
def test_server_mode_returns_404_and_classic_login_still_works(client, settings) -> None:
    settings.LMS_FETCH_MODE = "server"

    response = client.post(URL, body(), format="json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert not User.objects.filter(moodle_username="student9").exists()


@pytest.mark.django_db
def test_classic_login_still_available_in_device_mode(
    client, settings, fake_clients, monkeypatch
) -> None:
    from apps.moodle.protocols import SiteInfo

    settings.LMS_FETCH_MODE = "device"
    fake_clients.moodle.add_user(
        "student1", "secret", SiteInfo(moodle_user_id=1, full_name="One"), token="tok-1"
    )
    import apps.accounts.api.views as views_module

    monkeypatch.setattr(
        views_module,
        "_login_service",
        lambda: views_module.LoginWithLms(
            auth_client=fake_clients.moodle, data_client=fake_clients.moodle
        ),
    )

    response = client.post(
        "/api/v1/auth/login", {"username": "student1", "password": "secret"}, format="json"
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_device_login_is_throttled(client) -> None:
    statuses = [client.post(URL, body(), format="json").status_code for _ in range(6)]

    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429


@pytest.mark.django_db
def test_device_login_never_calls_moodle(client, fake_clients) -> None:
    fake_clients.moodle.unavailable = True  # any call would raise LmsUnavailable

    assert client.post(URL, body(), format="json").status_code == 200


@pytest.mark.django_db
def test_device_mismatch_message_is_translated(client) -> None:
    client.post(URL, body(), format="json")

    ar = client.post(
        URL, body(device_secret=OTHER_SECRET), format="json", HTTP_ACCEPT_LANGUAGE="ar"
    )
    en = client.post(
        URL, body(device_secret=OTHER_SECRET), format="json", HTTP_ACCEPT_LANGUAGE="en"
    )

    assert ar.json()["error"]["message"] != en.json()["error"]["message"]
    assert "جهاز" in ar.json()["error"]["message"]
