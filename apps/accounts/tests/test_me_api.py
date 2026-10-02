from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.moodle.models import MoodleAccount
from apps.notifications.models import Device, Notification, TelegramLink
from apps.notifications.tests.factories import (
    DeviceFactory,
    NotificationFactory,
    TelegramLinkFactory,
)
from apps.reminders.models import ReminderRule, ScheduledReminder
from apps.reminders.services.rules import create_default_reminder_rules
from apps.schedule.models import Enrollment, Item
from apps.schedule.tests.factories import EnrollmentFactory, MoodleQuizItemFactory

pytestmark = pytest.mark.django_db


def test_me_contract(api, user) -> None:
    body = api.get("/api/v1/me").json()

    assert body == {
        "id": str(user.id),
        "full_name": user.full_name,
        "moodle_username": user.moodle_username,
        "email": user.email,
        "language": "ar",
        "timezone": "Africa/Cairo",
        "telegram_linked": False,
        "onboarding": {"defaults_confirmed": False},
    }


def test_patch_me_validates_timezone(api) -> None:
    assert api.patch("/api/v1/me", {"timezone": "Nowhere/City"}, format="json").status_code == 400
    ok = api.patch("/api/v1/me", {"language": "en", "timezone": "UTC"}, format="json")
    assert ok.status_code == 200
    assert ok.json()["language"] == "en"


def test_delete_account_cascades_personal_data(api, user) -> None:
    account = MoodleAccount(user=user, site_url="https://lms", moodle_user_id=1)
    account.set_token("secret-token")
    account.save()
    DeviceFactory(user=user)
    TelegramLinkFactory(user=user)
    NotificationFactory(user=user)
    create_default_reminder_rules(user)
    EnrollmentFactory(user=user)
    item = MoodleQuizItemFactory(user=user)
    ScheduledReminder.objects.create(
        user=user,
        item=item,
        offset_minutes=60,
        channel="push",
        send_at=timezone.now() + timedelta(hours=1),
    )

    assert api.delete("/api/v1/me").status_code == 204

    assert not User.objects.filter(pk=user.pk).exists()
    for model in (
        MoodleAccount,
        Device,
        TelegramLink,
        Notification,
        ReminderRule,
        Enrollment,
        Item,
        ScheduledReminder,
    ):
        assert not model.objects.exists(), model


def test_login_creates_default_rules(api) -> None:
    from apps.accounts.services.auth import LoginWithLms
    from apps.moodle.integrations.fake_client import FakeMoodleClient
    from apps.moodle.protocols import SiteInfo

    client = FakeMoodleClient()
    client.add_user("new-student", "pw", SiteInfo(moodle_user_id=9, full_name="New"), token="t9")

    result = LoginWithLms(auth_client=client, data_client=client)("new-student", "pw")

    assert ReminderRule.objects.filter(user=result.user).count() == 4
