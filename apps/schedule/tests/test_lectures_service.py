from datetime import UTC, date, datetime, time, timedelta

import pytest
from freezegun import freeze_time

from apps.core.exceptions import ValidationAppError
from apps.notifications.tests.factories import DeviceFactory
from apps.reminders.models import ScheduledReminder
from apps.schedule.models import Item, LectureSchedule
from apps.schedule.services import lectures as lecture_services

# Tuesday 1 Dec 2026, 10:00 UTC. Cairo is UTC+2 in December.
NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _frozen_clock():  # type: ignore[no-untyped-def]
    with freeze_time(NOW):
        yield


def _create(user, scheduler, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "title": "M110 lecture",
        "weekdays": [0, 2],  # Monday, Wednesday
        "start_time": time(18, 0),
        "duration_minutes": 90,
        "starts_on": date(2026, 11, 1),
        "ends_on": date(2027, 1, 31),
        "location": "Room 5",
    }
    data.update(overrides)
    return lecture_services.create_lecture_schedule(user, scheduler=scheduler, **data)


def test_create_generates_every_occurrence_until_ends_on(user, scheduler) -> None:
    DeviceFactory(user=user)

    schedule = _create(user, scheduler)

    items = list(Item.objects.filter(lecture_schedule=schedule).order_by("scheduled_at"))
    # Mondays and Wednesdays from Wed 2 Dec 2026 to Wed 27 Jan 2027 (past ones skipped)
    assert len(items) == 17
    assert items[0].scheduled_at == datetime(2026, 12, 2, 16, 0, tzinfo=UTC)
    assert items[-1].scheduled_at == datetime(2027, 1, 27, 16, 0, tzinfo=UTC)
    assert all(i.type == "lecture" and i.source == "manual" for i in items)
    assert items[0].ends_at == items[0].scheduled_at + timedelta(minutes=90)
    assert schedule.timezone == "Africa/Cairo"
    assert ScheduledReminder.objects.filter(item=items[0], offset_minutes=30).count() == 1
    assert ScheduledReminder.objects.filter(item=items[-1], offset_minutes=30).count() == 1


def test_four_month_weekly_schedule_has_every_occurrence(user, scheduler) -> None:
    schedule = _create(
        user, scheduler, weekdays=[5], starts_on=date(2026, 12, 5), ends_on=date(2027, 3, 31)
    )

    moments = list(
        Item.objects.filter(lecture_schedule=schedule)
        .order_by("scheduled_at")
        .values_list("scheduled_at", flat=True)
    )
    assert len(moments) == 17  # every Saturday, 5 Dec 2026 .. 27 Mar 2027
    assert moments[-1] == datetime(2027, 3, 27, 16, 0, tzinfo=UTC)


def test_expansion_is_idempotent(user, scheduler) -> None:
    schedule = _create(user, scheduler)

    created = lecture_services.expand_lecture_schedule(schedule, scheduler=scheduler)

    assert created == 0
    assert Item.objects.filter(lecture_schedule=schedule).count() == 17


def test_daily_expansion_only_fills_gaps(user, scheduler) -> None:
    schedule = _create(user, scheduler)
    Item.objects.filter(
        lecture_schedule=schedule, scheduled_at=datetime(2026, 12, 16, 16, 0, tzinfo=UTC)
    ).delete()

    total = lecture_services.expand_lecture_schedules(scheduler=scheduler, today=date(2026, 12, 8))

    assert total == 1
    assert Item.objects.filter(lecture_schedule=schedule).count() == 17


def test_update_regenerates_future_occurrences(user, scheduler) -> None:
    DeviceFactory(user=user)
    schedule = _create(user, scheduler)

    lecture_services.update_lecture_schedule(
        schedule, scheduler=scheduler, weekdays=[3], start_time=time(9, 30)
    )

    items = list(Item.objects.filter(lecture_schedule=schedule).order_by("scheduled_at"))
    # Every Thursday, 3 Dec 2026 .. 28 Jan 2027
    assert len(items) == 9
    assert items[0].scheduled_at == datetime(2026, 12, 3, 7, 30, tzinfo=UTC)
    assert items[-1].scheduled_at == datetime(2027, 1, 28, 7, 30, tzinfo=UTC)
    assert ScheduledReminder.objects.filter(item__lecture_schedule=schedule).exists()


def test_delete_removes_future_and_keeps_past(user, scheduler) -> None:
    schedule = _create(user, scheduler)
    past = Item.objects.create(
        user=user,
        lecture_schedule=schedule,
        type="lecture",
        source="manual",
        title="Past lecture",
        scheduled_at=NOW - timedelta(days=1),
    )

    lecture_services.delete_lecture_schedule(schedule)

    assert not LectureSchedule.objects.filter(pk=schedule.pk).exists()
    past.refresh_from_db()
    assert past.lecture_schedule_id is None
    assert Item.objects.filter(user=user).count() == 1


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"weekdays": []}, "weekdays"),
        ({"weekdays": [1, 1]}, "weekdays"),
        ({"weekdays": [7]}, "weekdays"),
        ({"ends_on": date(2026, 10, 1)}, "ends_on"),
        ({"ends_on": date(2028, 1, 1)}, "ends_on"),
        ({"duration_minutes": 0}, "duration_minutes"),
    ],
)
def test_validation(user, scheduler, overrides, field) -> None:
    with pytest.raises(ValidationAppError) as exc:
        _create(user, scheduler, **overrides)
    assert field in exc.value.details
