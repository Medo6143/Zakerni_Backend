"""``POST /me/lms/connect``, ``GET`` not connected, ``DELETE /me/lms``."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.moodle.models import MoodleAccount
from apps.notifications.models import Channel
from apps.reminders.models import ScheduledReminder
from apps.schedule.models import Enrollment, Item
from apps.schedule.tests.factories import EnrollmentFactory, ItemFactory, MoodleQuizItemFactory

CONNECT = "/api/v1/me/lms/connect"
LMS = "/api/v1/me/lms"
pytestmark = pytest.mark.django_db


def body(**overrides):  # type: ignore[no-untyped-def]
    data = {
        "username": "2012345",
        "moodle_user_id": 42,
        "full_name": "Student Name",
        "email": "s@example.com",
        "site_url": "https://lms.example.edu",
    }
    data.update(overrides)
    return data


def _reminder(item) -> ScheduledReminder:  # type: ignore[no-untyped-def]
    return ScheduledReminder.objects.create(
        user=item.user,
        item=item,
        offset_minutes=60,
        channel=Channel.PUSH,
        send_at=timezone.now() + timedelta(days=1),
    )


def test_connect_creates_tokenless_account(api, user) -> None:
    user.full_name = ""
    user.email = ""
    user.save()

    response = api.post(CONNECT, body(), format="json")

    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "status": "active",
        "last_synced_at": None,
        "last_sync_error": "",
    }
    account = MoodleAccount.objects.get(user=user)
    assert account.token_encrypted == ""
    assert (account.site_url, account.moodle_user_id) == ("https://lms.example.edu", 42)
    user.refresh_from_db()
    assert user.full_name == "Student Name"
    assert user.email == "s@example.com"


def test_connect_keeps_existing_name_and_email(api, user) -> None:
    user.full_name = "Mine"
    user.email = "mine@example.com"
    user.save()

    api.post(CONNECT, body(), format="json")

    user.refresh_from_db()
    assert (user.full_name, user.email) == ("Mine", "mine@example.com")


def test_connect_updates_existing_account_and_drops_token(api, user) -> None:
    account = MoodleAccount(user=user, site_url="https://old", moodle_user_id=1, status="expired")
    account.set_token("server-token")
    account.save()

    response = api.post(CONNECT, body(moodle_user_id=43), format="json")

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.moodle_user_id == 43
    assert account.status == MoodleAccount.Status.ACTIVE
    assert account.token_encrypted == ""
    assert MoodleAccount.objects.filter(user=user).count() == 1


def test_connect_allows_empty_name_and_email(api) -> None:
    assert api.post(CONNECT, body(full_name="", email=""), format="json").status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [{"site_url": "nope"}, {"moodle_user_id": 0}, {"username": ""}, {"email": "bad"}],
)
def test_connect_invalid_body(api, overrides) -> None:
    response = api.post(CONNECT, body(**overrides), format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_connect_requires_auth(anon_api) -> None:
    assert anon_api.post(CONNECT, body(), format="json").status_code == 401


def test_get_lms_not_connected(api) -> None:
    response = api.get(LMS)

    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "status": "not_connected",
        "last_synced_at": None,
        "last_sync_error": "",
    }


def test_get_lms_connected_has_connected_true(api) -> None:
    api.post(CONNECT, body(), format="json")

    assert api.get(LMS).json()["connected"] is True


INGEST = {"courses": [], "quizzes": [], "assignments": [], "events": []}


def test_ingest_without_account_is_404(api) -> None:
    assert api.post("/api/v1/me/lms/ingest", INGEST, format="json").status_code == 404


def test_ingest_works_after_connect(api) -> None:
    api.post(CONNECT, body(), format="json")

    assert api.post("/api/v1/me/lms/ingest", INGEST, format="json").status_code == 200


def test_disconnect_removes_moodle_data_and_keeps_the_rest(api, user) -> None:
    api.post(CONNECT, body(), format="json")
    moodle_item = MoodleQuizItemFactory(user=user)
    manual_item = ItemFactory(user=user)
    moodle_reminder = _reminder(moodle_item)
    manual_reminder = _reminder(manual_item)
    enrollment = EnrollmentFactory(user=user)

    response = api.delete(LMS)

    assert response.status_code == 204
    assert not MoodleAccount.objects.filter(user=user).exists()
    moodle_item.refresh_from_db()
    manual_item.refresh_from_db()
    assert moodle_item.deleted_at is not None
    assert manual_item.deleted_at is None
    moodle_reminder.refresh_from_db()
    manual_reminder.refresh_from_db()
    assert moodle_reminder.status == ScheduledReminder.Status.CANCELLED
    assert manual_reminder.status == ScheduledReminder.Status.PENDING
    enrollment.refresh_from_db()
    assert enrollment.is_active is False
    assert api.get(LMS).json()["connected"] is False


def test_disconnect_does_not_touch_other_users(api, user) -> None:
    api.post(CONNECT, body(), format="json")
    other = UserFactory()
    MoodleAccount.objects.create(user=other, site_url="https://lms", moodle_user_id=9)
    other_item = MoodleQuizItemFactory(user=other)
    other_reminder = _reminder(other_item)
    other_enrollment = EnrollmentFactory(user=other)

    api.delete(LMS)

    assert MoodleAccount.objects.filter(user=other).exists()
    assert Item.objects.get(pk=other_item.pk).deleted_at is None
    other_reminder.refresh_from_db()
    assert other_reminder.status == ScheduledReminder.Status.PENDING
    assert Enrollment.objects.get(pk=other_enrollment.pk).is_active is True


def test_disconnect_without_account_is_noop(api) -> None:
    assert api.delete(LMS).status_code == 204


def test_disconnect_requires_auth(anon_api) -> None:
    assert anon_api.delete(LMS).status_code == 401
