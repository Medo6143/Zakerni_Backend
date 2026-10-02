from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.notifications.tests.factories import DeviceFactory, TelegramLinkFactory
from apps.reminders.models import ItemReminderOverride, ReminderRule, ScheduledReminder
from apps.reminders.services.rules import create_default_reminder_rules
from apps.schedule.tests.factories import MoodleQuizItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _frozen_clock():  # type: ignore[no-untyped-def]
    with freeze_time(NOW):
        yield


def test_default_rules_created_idempotently(user) -> None:
    create_default_reminder_rules(user)
    create_default_reminder_rules(user)

    rules = {r.item_type: r for r in ReminderRule.objects.filter(user=user)}
    assert set(rules) == {"quiz", "tma", "exam", "lecture"}
    assert rules["quiz"].offsets_minutes == [1440, 180]
    assert rules["tma"].offsets_minutes == [4320, 1440]
    assert rules["exam"].offsets_minutes == [4320, 1440]
    assert rules["lecture"].offsets_minutes == [30]
    # Telegram is off until linked
    assert not any(r.telegram_enabled for r in rules.values())
    assert all(r.push_enabled for r in rules.values())


def test_default_rules_with_linked_telegram(user) -> None:
    TelegramLinkFactory(user=user)

    create_default_reminder_rules(user)

    enabled = set(
        ReminderRule.objects.filter(user=user, telegram_enabled=True).values_list(
            "item_type", flat=True
        )
    )
    assert enabled == {"quiz", "tma", "exam"}


def test_list_rules_always_four(api) -> None:
    response = api.get("/api/v1/reminder-rules")

    assert response.status_code == 200
    body = response.json()
    assert [r["item_type"] for r in body] == ["exam", "lecture", "quiz", "tma"]
    assert body[2] == {
        "item_type": "quiz",
        "offsets_minutes": [1440, 180],
        "push_enabled": True,
        "telegram_enabled": False,
    }


def test_rules_require_auth(anon_api) -> None:
    assert anon_api.get("/api/v1/reminder-rules").status_code == 401


def test_update_rule_reschedules_future_items(api, user) -> None:
    DeviceFactory(user=user)
    item = MoodleQuizItemFactory(user=user)

    response = api.put(
        "/api/v1/reminder-rules/quiz",
        {"offsets_minutes": [60, 2880], "push_enabled": True, "telegram_enabled": False},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["offsets_minutes"] == [2880, 60]
    assert set(
        ScheduledReminder.objects.filter(item=item, status="pending").values_list(
            "offset_minutes", flat=True
        )
    ) == {2880, 60}


@pytest.mark.parametrize(
    "offsets",
    [[], [1, 60], [60, 60], [20161], [5, 10, 15, 20, 25, 30]],
)
def test_update_rule_validation(api, offsets) -> None:
    response = api.put(
        "/api/v1/reminder-rules/quiz",
        {"offsets_minutes": offsets, "push_enabled": True, "telegram_enabled": False},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert "offsets_minutes" in response.json()["error"]["details"]


def test_update_rule_unknown_type_is_404(api) -> None:
    response = api.put(
        "/api/v1/reminder-rules/homework",
        {"offsets_minutes": [60], "push_enabled": True, "telegram_enabled": False},
        format="json",
    )

    assert response.status_code == 404


def test_telegram_requires_link(api, user) -> None:
    payload = {"offsets_minutes": [60], "push_enabled": True, "telegram_enabled": True}

    response = api.put("/api/v1/reminder-rules/quiz", payload, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "telegram_not_linked"

    TelegramLinkFactory(user=user)
    assert api.put("/api/v1/reminder-rules/quiz", payload, format="json").status_code == 200


def test_confirm_defaults_sets_onboarding_flag(api) -> None:
    assert api.get("/api/v1/me").json()["onboarding"] == {"defaults_confirmed": False}

    response = api.post("/api/v1/reminder-rules/confirm-defaults")

    assert response.status_code == 204
    assert api.get("/api/v1/me").json()["onboarding"] == {"defaults_confirmed": True}


def test_item_override_put_and_delete(api, user) -> None:
    DeviceFactory(user=user)
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=3))

    response = api.put(
        f"/api/v1/items/{item.id}/reminders", {"offsets_minutes": [120]}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reminders"] == {
        "offsets_minutes": [120],
        "is_override": True,
        "next_at": "2026-12-04T08:00:00Z",
    }
    assert ItemReminderOverride.objects.filter(item=item).exists()

    assert api.delete(f"/api/v1/items/{item.id}/reminders").status_code == 204
    assert not ItemReminderOverride.objects.filter(item=item).exists()
    detail = api.get(f"/api/v1/items/{item.id}").json()
    assert detail["reminders"]["offsets_minutes"] == [1440, 180]
    assert detail["reminders"]["is_override"] is False


def test_item_override_validation_and_not_found(api) -> None:
    item = MoodleQuizItemFactory()

    response = api.put(
        f"/api/v1/items/{item.id}/reminders", {"offsets_minutes": [120]}, format="json"
    )

    assert response.status_code == 404
