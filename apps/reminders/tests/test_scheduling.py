from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.notifications.channels.fake import FakePushChannel, FakeTelegramChannel
from apps.notifications.tests.factories import DeviceFactory, TelegramLinkFactory
from apps.reminders.models import ItemReminderOverride, ReminderRule, ScheduledReminder
from apps.reminders.services.rules import create_default_reminder_rules
from apps.reminders.services.scheduling import ReminderSchedulingService
from apps.schedule.tests.factories import EnrollmentFactory, ItemFactory, MoodleQuizItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _frozen_clock():  # type: ignore[no-untyped-def]
    with freeze_time(NOW):
        yield


def _rows(item, status="pending"):  # type: ignore[no-untyped-def]
    return {
        (r.offset_minutes, r.channel): r.send_at
        for r in ScheduledReminder.objects.filter(item=item, status=status)
    }


def _both_channels() -> ReminderSchedulingService:
    return ReminderSchedulingService(
        channels={"push": FakePushChannel(), "telegram": FakeTelegramChannel()}
    )


@pytest.mark.parametrize(
    ("item_type", "days_ahead", "expected_offsets"),
    [
        ("quiz", 5, {1440, 180}),
        ("tma", 5, {4320, 1440}),
        ("exam", 5, {4320, 1440}),
        ("lecture", 5, {30}),
        # only offsets whose send_at is still in the future are scheduled
        ("tma", 2, {1440}),
        ("quiz", 0.1, set()),  # 2.4 h ahead: 1440 and 180 are both past
    ],
)
def test_default_offsets(user, item_type, days_ahead, expected_offsets) -> None:
    item = ItemFactory(
        user=user,
        type=item_type,
        source="moodle" if item_type in ("quiz", "tma") else "manual",
        scheduled_at=NOW + timedelta(days=days_ahead),
    )
    create_default_reminder_rules(user)
    ReminderRule.objects.filter(user=user).update(telegram_enabled=False)

    _both_channels().schedule_for_item(item)

    rows = _rows(item)
    assert {offset for offset, _channel in rows} == expected_offsets
    for (offset, _channel), send_at in rows.items():
        assert send_at == item.scheduled_at - timedelta(minutes=offset)


def test_channels_are_rule_channels_intersected_with_connected(user, scheduler) -> None:
    item = MoodleQuizItemFactory(user=user)
    # No device and no Telegram: nothing to deliver through.
    scheduler.schedule_for_item(item)
    assert _rows(item) == {}

    DeviceFactory(user=user)
    TelegramLinkFactory(user=user)
    ReminderRule.objects.filter(user=user, item_type="quiz").update(telegram_enabled=True)
    scheduler.schedule_for_item(item)
    assert {channel for _o, channel in _rows(item)} == {"push", "telegram"}

    ReminderRule.objects.filter(user=user, item_type="quiz").update(push_enabled=False)
    scheduler.schedule_for_item(item)
    assert {channel for _o, channel in _rows(item)} == {"telegram"}
    assert len(_rows(item, "cancelled")) == 2


def test_override_replaces_rule_offsets(user) -> None:
    item = MoodleQuizItemFactory(user=user)
    ItemReminderOverride.objects.create(item=item, offsets_minutes=[60])

    _both_channels().schedule_for_item(item)

    assert set(_rows(item)) == {(60, "push")}


def test_muted_item_past_item_and_deleted_item_cancel_all(user) -> None:
    service = _both_channels()
    item = MoodleQuizItemFactory(user=user)
    service.schedule_for_item(item)
    assert len(_rows(item)) == 2

    item.is_muted = True
    service.schedule_for_item(item)
    assert _rows(item) == {}

    item.is_muted = False
    service.schedule_for_item(item)
    assert len(_rows(item)) == 2
    item.deleted_at = NOW
    service.schedule_for_item(item)
    assert _rows(item) == {}

    past = MoodleQuizItemFactory(user=user, scheduled_at=NOW - timedelta(hours=1))
    service.schedule_for_item(past)
    assert _rows(past) == {}


def test_course_mute(user) -> None:
    enrollment = EnrollmentFactory(user=user, is_muted=True)
    item = MoodleQuizItemFactory(user=user, course=enrollment.course)

    _both_channels().schedule_for_item(item)

    assert _rows(item) == {}


def test_reschedule_updates_send_at_without_duplicates(user) -> None:
    service = _both_channels()
    item = MoodleQuizItemFactory(user=user)
    service.schedule_for_item(item)
    item.scheduled_at = item.scheduled_at + timedelta(days=1)
    item.save()

    service.schedule_for_item(item)
    service.schedule_for_item(item)

    assert ScheduledReminder.objects.filter(item=item).count() == 2
    assert _rows(item)[(1440, "push")] == item.scheduled_at - timedelta(minutes=1440)


def test_sent_reminder_is_not_rearmed_unless_item_moves_later(user) -> None:
    service = _both_channels()
    item = MoodleQuizItemFactory(user=user)
    service.schedule_for_item(item)
    ScheduledReminder.objects.filter(item=item, offset_minutes=1440).update(
        status="sent", sent_at=NOW
    )

    service.schedule_for_item(item)
    assert ScheduledReminder.objects.get(item=item, offset_minutes=1440).status == "sent"

    item.scheduled_at = item.scheduled_at - timedelta(hours=1)  # moved earlier
    item.save()
    service.schedule_for_item(item)
    assert ScheduledReminder.objects.get(item=item, offset_minutes=1440).status == "sent"

    item.scheduled_at = item.scheduled_at + timedelta(days=3)  # deadline extended
    item.save()
    service.schedule_for_item(item)
    row = ScheduledReminder.objects.get(item=item, offset_minutes=1440)
    assert row.status == "pending"
    assert row.send_at == item.scheduled_at - timedelta(minutes=1440)


def test_reschedule_for_user_filters(user) -> None:
    service = _both_channels()
    quiz = MoodleQuizItemFactory(user=user)
    exam = ItemFactory(user=user)

    count = service.reschedule_for_user(user, item_type="quiz")

    assert count == 1
    assert len(_rows(quiz)) == 2
    assert _rows(exam) == {}


def test_cancel_for_item(user) -> None:
    service = _both_channels()
    item = MoodleQuizItemFactory(user=user)
    service.schedule_for_item(item)

    service.cancel_for_item(item)

    assert _rows(item) == {}
    assert len(_rows(item, "cancelled")) == 2


def test_rules_are_created_on_demand(user) -> None:
    item = MoodleQuizItemFactory(user=user)
    assert not ReminderRule.objects.filter(user=user).exists()

    _both_channels().schedule_for_item(item)

    assert ReminderRule.objects.filter(user=user).count() == 4
