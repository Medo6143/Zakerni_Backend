from datetime import UTC, datetime

import pytest
from freezegun import freeze_time

from apps.accounts.tests.factories import UserFactory
from apps.notifications.channels.fcm import FcmChannel
from apps.notifications.integrations.fakes import FakePushSender
from apps.notifications.models import Device
from apps.notifications.protocols import Message
from apps.notifications.services.devices import register_device
from apps.notifications.tests.factories import DeviceFactory
from apps.reminders.models import ScheduledReminder
from apps.schedule.tests.factories import MoodleQuizItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db

MESSAGE = Message(title="T", body="B", data={"kind": "reminder"})


@pytest.fixture(autouse=True)
def _frozen_clock():  # type: ignore[no-untyped-def]
    with freeze_time(NOW):
        yield


def test_register_device_creates_then_upserts(user, scheduler) -> None:
    first = register_device(user, fcm_token="tok-1", platform="android", scheduler=scheduler)
    second = register_device(
        user, fcm_token="tok-1", platform="android", app_version="1.1", scheduler=scheduler
    )

    assert first.created is True
    assert second.created is False
    assert Device.objects.get(fcm_token="tok-1").app_version == "1.1"


def test_token_moves_to_latest_user(user, scheduler) -> None:
    other = UserFactory()
    DeviceFactory(user=other, fcm_token="shared")

    register_device(user, fcm_token="shared", platform="ios", scheduler=scheduler)

    device = Device.objects.get(fcm_token="shared")
    assert device.user == user and device.platform == "ios"


def test_first_device_schedules_push_reminders(user, scheduler) -> None:
    item = MoodleQuizItemFactory(user=user)
    scheduler.schedule_for_item(item)
    assert not ScheduledReminder.objects.filter(item=item, status="pending").exists()

    register_device(user, fcm_token="tok-1", platform="android", scheduler=scheduler)

    assert (
        ScheduledReminder.objects.filter(item=item, status="pending", channel="push").count() == 2
    )


def test_devices_endpoints(api, user) -> None:
    payload = {
        "fcm_token": "tok-xyz:APA91",
        "platform": "android",
        "app_version": "1.0.0",
        "os_version": "14",
        "model": "Pixel 8",
    }

    created = api.post("/api/v1/devices", payload, format="json")
    again = api.post("/api/v1/devices", payload, format="json")

    assert created.status_code == 201
    assert again.status_code == 200
    assert "fcm_token" not in created.json()
    assert api.post("/api/v1/devices", {"platform": "web"}, format="json").status_code == 400

    assert api.delete("/api/v1/devices/tok-xyz:APA91").status_code == 204
    assert Device.objects.get(fcm_token="tok-xyz:APA91").is_active is False


def test_logout_deactivates_device(api, user) -> None:
    from rest_framework_simplejwt.tokens import RefreshToken

    DeviceFactory(user=user, fcm_token="tok-logout")
    refresh = str(RefreshToken.for_user(user))

    response = api.post(
        "/api/v1/auth/logout", {"refresh": refresh, "fcm_token": "tok-logout"}, format="json"
    )

    assert response.status_code == 204
    assert Device.objects.get(fcm_token="tok-logout").is_active is False


def test_fcm_channel_sends_to_all_active_devices(user) -> None:
    DeviceFactory(user=user, fcm_token="a")
    DeviceFactory(user=user, fcm_token="b")
    DeviceFactory(user=user, fcm_token="c", is_active=False)
    sender = FakePushSender()
    channel = FcmChannel(sender)

    result = channel.send(user, MESSAGE)

    assert result.ok
    assert sorted(token for token, _m in sender.sent) == ["a", "b"]


def test_invalid_fcm_token_deactivates_device(user) -> None:
    DeviceFactory(user=user, fcm_token="dead")
    sender = FakePushSender(invalid_tokens={"dead"})
    channel = FcmChannel(sender)

    result = channel.send(user, MESSAGE)

    assert result.ok is False
    assert result.retryable is False
    assert Device.objects.get(fcm_token="dead").is_active is False
    assert channel.is_available_for(user) is False


def test_fcm_channel_partial_failure_is_success(user) -> None:
    DeviceFactory(user=user, fcm_token="dead")
    DeviceFactory(user=user, fcm_token="alive")
    channel = FcmChannel(FakePushSender(invalid_tokens={"dead"}))

    assert channel.send(user, MESSAGE).ok is True
    assert Device.objects.get(fcm_token="dead").is_active is False


def test_fcm_channel_retryable_and_no_device(user) -> None:
    channel = FcmChannel(FakePushSender(retryable_failure=True))
    assert channel.send(user, MESSAGE).error == "no_active_device"

    DeviceFactory(user=user)
    result = channel.send(user, MESSAGE)
    assert result.ok is False and result.retryable is True


def test_firebase_sender_without_credentials_never_raises() -> None:
    from apps.notifications.integrations.fcm_sender import FirebasePushSender

    result = FirebasePushSender(credentials_file="").send("tok", MESSAGE)

    assert result.ok is False
    assert result.error == "fcm_not_configured"
