from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.core.exceptions import ItemNotEditable, ValidationAppError
from apps.notifications.tests.factories import DeviceFactory
from apps.reminders.models import ScheduledReminder
from apps.schedule.services import courses as course_services
from apps.schedule.services import items as item_services
from apps.schedule.tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    ItemFactory,
    MoodleQuizItemFactory,
)

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _frozen_clock():  # type: ignore[no-untyped-def]
    with freeze_time(NOW):
        yield


def _pending(item):  # type: ignore[no-untyped-def]
    return set(
        ScheduledReminder.objects.filter(item=item, status="pending").values_list(
            "offset_minutes", "channel"
        )
    )


def test_create_exam_schedules_default_reminders(user, scheduler) -> None:
    DeviceFactory(user=user)
    course = EnrollmentFactory(user=user).course

    item = item_services.create_manual_item(
        user,
        title="MTA",
        scheduled_at=NOW + timedelta(days=5),
        ends_at=NOW + timedelta(days=5, hours=2),
        course_id=course.id,
        location="Hall 3",
        scheduler=scheduler,
    )

    assert item.type == "exam" and item.source == "manual"
    assert item.course == course
    assert _pending(item) == {(4320, "push"), (1440, "push")}


def test_create_exam_rejects_end_before_start(user, scheduler) -> None:
    with pytest.raises(ValidationAppError) as exc:
        item_services.create_manual_item(
            user,
            title="MTA",
            scheduled_at=NOW + timedelta(days=5),
            ends_at=NOW + timedelta(days=4),
            scheduler=scheduler,
        )
    assert "ends_at" in exc.value.details


def test_create_exam_rejects_course_not_enrolled(user, scheduler) -> None:
    with pytest.raises(ValidationAppError):
        item_services.create_manual_item(
            user,
            title="MTA",
            scheduled_at=NOW + timedelta(days=5),
            course_id=CourseFactory().id,
            scheduler=scheduler,
        )


def test_update_exam_reschedules(user, scheduler) -> None:
    DeviceFactory(user=user)
    item = item_services.create_manual_item(
        user, title="MTA", scheduled_at=NOW + timedelta(days=5), scheduler=scheduler
    )
    new_time = NOW + timedelta(days=8)

    item_services.update_manual_item(
        item, scheduled_at=new_time, title="Final", scheduler=scheduler
    )

    item.refresh_from_db()
    assert item.title == "Final"
    row = ScheduledReminder.objects.get(item=item, offset_minutes=4320)
    assert row.send_at == new_time - timedelta(minutes=4320)


def test_moodle_item_is_not_editable(user, scheduler) -> None:
    item = MoodleQuizItemFactory(user=user)

    with pytest.raises(ItemNotEditable):
        item_services.update_manual_item(item, title="Hacked", scheduler=scheduler)
    with pytest.raises(ItemNotEditable):
        item_services.delete_manual_item(item, scheduler=scheduler)


def test_delete_exam_soft_deletes_and_cancels(user, scheduler) -> None:
    DeviceFactory(user=user)
    item = item_services.create_manual_item(
        user, title="MTA", scheduled_at=NOW + timedelta(days=5), scheduler=scheduler
    )

    item_services.delete_manual_item(item, scheduler=scheduler)

    item.refresh_from_db()
    assert item.deleted_at == NOW
    assert _pending(item) == set()


def test_mute_and_unmute_item(user, scheduler) -> None:
    DeviceFactory(user=user)
    item = MoodleQuizItemFactory(user=user)
    scheduler.schedule_for_item(item)
    assert _pending(item) == {(1440, "push"), (180, "push")}

    item_services.set_item_muted(item, is_muted=True, scheduler=scheduler)
    assert _pending(item) == set()

    item_services.set_item_muted(item, is_muted=False, scheduler=scheduler)
    assert _pending(item) == {(1440, "push"), (180, "push")}


def test_mute_course_cancels_and_unmute_restores(user, scheduler) -> None:
    DeviceFactory(user=user)
    enrollment = EnrollmentFactory(user=user)
    item = MoodleQuizItemFactory(user=user, course=enrollment.course)
    other = MoodleQuizItemFactory(user=user)
    scheduler.schedule_for_item(item)
    scheduler.schedule_for_item(other)

    course_services.set_course_muted(enrollment, is_muted=True, scheduler=scheduler)
    assert _pending(item) == set()
    assert len(_pending(other)) == 2

    course_services.set_course_muted(enrollment, is_muted=False, scheduler=scheduler)
    assert len(_pending(item)) == 2


@freeze_time(NOW)
def test_item_is_editable_flag(user) -> None:
    assert ItemFactory(user=user).is_editable is True
    assert MoodleQuizItemFactory(user=user).is_editable is False


def test_create_manual_quiz_uses_the_quiz_rule(user, scheduler) -> None:
    DeviceFactory(user=user)

    item = item_services.create_manual_item(
        user,
        type="quiz",
        title="Quiz 3",
        scheduled_at=NOW + timedelta(days=5),
        available_from=NOW + timedelta(days=4),
        scheduler=scheduler,
    )

    assert item.type == "quiz" and item.source == "manual"
    assert item.available_from == NOW + timedelta(days=4)
    assert item.is_editable is True
    assert _pending(item) == {(1440, "push"), (180, "push")}


def test_create_manual_quiz_rejects_open_after_close(user, scheduler) -> None:
    with pytest.raises(ValidationAppError) as exc:
        item_services.create_manual_item(
            user,
            type="quiz",
            title="Quiz 3",
            scheduled_at=NOW + timedelta(days=5),
            available_from=NOW + timedelta(days=6),
            scheduler=scheduler,
        )
    assert "available_from" in exc.value.details


def test_create_manual_item_rejects_lecture_and_tma(user, scheduler) -> None:
    for item_type in ("lecture", "tma"):
        with pytest.raises(ValidationAppError):
            item_services.create_manual_item(
                user,
                type=item_type,
                title="X",
                scheduled_at=NOW + timedelta(days=5),
                scheduler=scheduler,
            )


def test_update_manual_quiz_available_from(user, scheduler) -> None:
    item = item_services.create_manual_item(
        user, type="quiz", title="Quiz", scheduled_at=NOW + timedelta(days=5), scheduler=scheduler
    )

    item_services.update_manual_item(
        item, available_from=NOW + timedelta(days=1), scheduler=scheduler
    )

    item.refresh_from_db()
    assert item.available_from == NOW + timedelta(days=1)
