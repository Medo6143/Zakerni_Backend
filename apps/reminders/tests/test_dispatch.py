import threading
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from freezegun import freeze_time

from apps.notifications.channels.fake import FakePushChannel, FakeTelegramChannel
from apps.notifications.models import Notification
from apps.notifications.protocols import DeliveryResult
from apps.notifications.tests.factories import DeviceFactory
from apps.reminders.models import ScheduledReminder
from apps.reminders.services.dispatch import DispatchDueReminders
from apps.schedule.tests.factories import MoodleQuizItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)


def _reminder(item, *, channel="push", offset=1440, send_at=None, status="pending"):  # type: ignore[no-untyped-def]
    return ScheduledReminder.objects.create(
        user=item.user,
        item=item,
        offset_minutes=offset,
        channel=channel,
        send_at=send_at or NOW - timedelta(minutes=1),
        status=status,
    )


@pytest.fixture
def push() -> FakePushChannel:
    return FakePushChannel()


@pytest.fixture
def telegram() -> FakeTelegramChannel:
    return FakeTelegramChannel()


@pytest.fixture
def dispatch(push, telegram) -> DispatchDueReminders:
    return DispatchDueReminders(channels={"push": push, "telegram": telegram})


@pytest.mark.django_db
@freeze_time(NOW)
def test_sends_due_reminders_and_writes_history(user, dispatch, push) -> None:
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    due = _reminder(item)
    future = _reminder(item, offset=180, send_at=NOW + timedelta(minutes=5))

    stats = dispatch()

    assert stats.sent == 1
    due.refresh_from_db()
    future.refresh_from_db()
    assert due.status == "sent" and due.sent_at == NOW and due.attempts == 1
    assert future.status == "pending"
    assert len(push.sent) == 1
    message = push.sent[0][1]
    assert message.data == {
        "kind": "reminder",
        "item_id": str(item.id),
        "route": f"/calendar?item={item.id}",
    }
    notification = Notification.objects.get(user=user)
    assert notification.kind == "reminder" and notification.item == item


@pytest.mark.django_db
@freeze_time(NOW)
def test_two_channels_write_one_history_row(user, dispatch, push, telegram) -> None:
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    _reminder(item, channel="push")
    _reminder(item, channel="telegram")

    stats = dispatch()

    assert stats.sent == 2
    assert len(push.sent) == 1 and len(telegram.sent) == 1
    assert Notification.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_no_double_send_when_dispatched_twice(user, dispatch, push) -> None:
    with freeze_time(NOW):
        item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
        _reminder(item)
        dispatch()
        dispatch()
    with freeze_time(NOW + timedelta(minutes=5)):
        dispatch()

    assert len(push.sent) == 1
    assert Notification.objects.count() == 1


@pytest.mark.django_db
@freeze_time(NOW)
def test_row_claimed_by_another_worker_is_not_sent(user, push, telegram, monkeypatch) -> None:
    """Simulates the race: worker B lists the row, worker A sends it first. B re-checks
    ``status=pending`` under the row lock and skips it."""
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    row = _reminder(item)
    worker_b = DispatchDueReminders(channels={"push": push, "telegram": telegram})
    import apps.reminders.services.dispatch as dispatch_module

    def listed_then_taken(now, limit):  # type: ignore[no-untyped-def]
        ids = [row.id]
        ScheduledReminder.objects.filter(id=row.id).update(status="sent")  # worker A
        return ids

    monkeypatch.setattr(dispatch_module, "due_reminder_ids", listed_then_taken)

    stats = worker_b()

    assert stats.sent == 0
    assert push.sent == []


@pytest.mark.django_db
@freeze_time(NOW)
def test_retryable_failure_retries_then_fails(user, dispatch, push) -> None:
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    row = _reminder(item)
    push.queue_results(*[DeliveryResult.failure("UnavailableError", retryable=True)] * 3)

    dispatch()
    row.refresh_from_db()
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.send_at == NOW + timedelta(minutes=2)

    with freeze_time(NOW + timedelta(minutes=2)):
        dispatch()
    row.refresh_from_db()
    assert row.status == "pending" and row.attempts == 2

    with freeze_time(NOW + timedelta(minutes=4)):
        dispatch()
    row.refresh_from_db()
    assert row.status == "failed"
    assert row.attempts == 3
    assert row.error == "UnavailableError"
    assert not Notification.objects.exists()


@pytest.mark.django_db
@freeze_time(NOW)
def test_non_retryable_failure_fails_immediately(user, dispatch, push) -> None:
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    row = _reminder(item)
    push.queue_results(DeliveryResult.failure("no_active_device"))

    stats = dispatch()

    row.refresh_from_db()
    assert stats.failed == 1
    assert row.status == "failed"


@pytest.mark.django_db
@freeze_time(NOW)
def test_late_reminders_are_skipped(user, dispatch, push) -> None:
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(hours=1))
    row = _reminder(item, send_at=NOW - timedelta(minutes=31))

    stats = dispatch()

    row.refresh_from_db()
    assert stats.skipped == 1
    assert row.status == "skipped" and row.error == "late"
    assert push.sent == []


@pytest.mark.django_db
@freeze_time(NOW)
def test_unavailable_channel_is_skipped(user, push, telegram) -> None:
    telegram.available = False
    dispatch = DispatchDueReminders(channels={"push": push, "telegram": telegram})
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    row = _reminder(item, channel="telegram")

    dispatch()

    row.refresh_from_db()
    assert row.status == "skipped" and row.error == "channel_unavailable"


@pytest.mark.django_db
@freeze_time(NOW)
def test_muted_item_is_cancelled_at_dispatch(user, dispatch, push) -> None:
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1), is_muted=True)
    row = _reminder(item)

    dispatch()

    row.refresh_from_db()
    assert row.status == "cancelled"
    assert push.sent == []


@pytest.mark.django_db
@freeze_time(NOW)
def test_end_to_end_with_real_fcm_channel(user, channels, fake_clients) -> None:
    DeviceFactory(user=user, fcm_token="tok-A")
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    _reminder(item)

    stats = DispatchDueReminders(channels=channels)()

    assert stats.sent == 1
    assert fake_clients.push.sent[0][0] == "tok-A"


@pytest.mark.skipif(connection.vendor != "postgresql", reason="needs row-level locks (PostgreSQL)")
@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_never_double_send(user) -> None:  # pragma: no cover - PG only
    item = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))
    for offset in range(5, 55):
        _reminder(item, offset=offset, send_at=NOW - timedelta(minutes=1))
    push = FakePushChannel()

    def worker() -> None:
        DispatchDueReminders(channels={"push": push})()
        connection.close()

    # Freeze once for all threads: freezegun's global state is not thread-safe, and
    # nested per-thread freezes corrupt it for every later test.
    with freeze_time(NOW):
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(push.sent) == 50
    assert ScheduledReminder.objects.filter(status="sent").count() == 50
