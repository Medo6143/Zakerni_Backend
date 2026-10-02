from datetime import UTC, date, datetime, time, timedelta

import pytest
from freezegun import freeze_time

from apps.accounts.tests.factories import UserFactory
from apps.notifications.models import Notification
from apps.notifications.tests.factories import DeviceFactory
from apps.reminders.models import ScheduledReminder
from apps.schedule.models import Item, ItemSource, ItemType, LectureSchedule
from apps.schedule.tests.factories import CourseFactory, EnrollmentFactory
from apps.sis.integrations.fake_client import FakeSisClient
from apps.sis.models import SisAccount, SisSyncLog
from apps.sis.protocols import SisScheduleEntry
from apps.sis.services.sync import SyncSisAccount

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
USERNAME = "2026123456"
PASSWORD = "sis-pass"


def lecture(day: date, code: str = "M110", **kw) -> SisScheduleEntry:  # type: ignore[no-untyped-def]
    values = {
        "start_time": time(10, 0),
        "end_time": time(12, 0),
        "location_en": "Room 101",
        "location_ar": "Room 101 AR",
        "lecturer_en": "Dr. Tutor",
        "lecturer_ar": "Dr. Tutor AR",
    }
    values.update(kw)
    return SisScheduleEntry(kind="lecture", day=day, course_code=code, **values)


def exam(day: date, name: str = "Final", code: str = "M110", **kw) -> SisScheduleEntry:  # type: ignore[no-untyped-def]
    values = {"start_time": time(9, 0), "end_time": time(11, 0), "location_en": "Hall A"}
    values.update(kw)
    return SisScheduleEntry(kind="exam", day=day, course_code=code, exam_name=name, **values)


@pytest.fixture
def sis() -> FakeSisClient:
    client = FakeSisClient()
    client.add_user(
        USERNAME,
        PASSWORD,
        [
            lecture(date(2026, 10, 4)),
            lecture(date(2026, 10, 11)),
            lecture(date(2026, 10, 18)),
            exam(date(2026, 12, 20)),
        ],
    )
    return client


@pytest.fixture
def account(db) -> SisAccount:
    user = UserFactory(language="en")
    DeviceFactory(user=user)
    account = SisAccount(user=user, username=USERNAME)
    account.set_password(PASSWORD)
    account.save()
    return account


@pytest.fixture
def enrollment(account):  # type: ignore[no-untyped-def]
    course = CourseFactory(code="M110-FALL26", name="Programming")
    return EnrollmentFactory(user=account.user, course=course)


@pytest.fixture
def sync(sis, scheduler, channels) -> SyncSisAccount:
    return SyncSisAccount(client=sis, scheduler=scheduler, channels=channels)


@freeze_time(NOW)
def test_exams_and_timetable_are_imported(sync, account, enrollment) -> None:
    result = sync(account)

    assert result.status == "success"
    assert result.items_created == 2  # one exam + one weekly timetable
    exam_item = Item.objects.get(user=account.user, type=ItemType.EXAM)
    assert exam_item.source == ItemSource.SIS
    assert exam_item.title == "M110 - Final"
    assert exam_item.location == "Hall A"
    # 09:00 Cairo (UTC+2 in December)
    assert exam_item.scheduled_at == datetime(2026, 12, 20, 7, 0, tzinfo=UTC)
    assert exam_item.ends_at == datetime(2026, 12, 20, 9, 0, tzinfo=UTC)
    assert exam_item.course_id == enrollment.course_id
    assert ScheduledReminder.objects.filter(item=exam_item).exists()

    schedule = LectureSchedule.objects.get(user=account.user)
    assert schedule.source == ItemSource.SIS
    assert schedule.weekdays == [6]  # Sunday
    assert schedule.start_time == time(10, 0)
    assert schedule.duration_minutes == 120
    assert schedule.starts_on == date(2026, 10, 4)
    assert schedule.ends_on == date(2026, 10, 18)
    assert schedule.location == "Room 101"
    assert schedule.course_id == enrollment.course_id
    lectures = Item.objects.filter(lecture_schedule=schedule).order_by("scheduled_at")
    assert lectures.count() == 3
    assert {i.source for i in lectures} == {ItemSource.SIS}
    assert all(not i.is_editable for i in lectures)

    enrollment.refresh_from_db()
    assert enrollment.tutor_name == "Dr. Tutor"
    account.refresh_from_db()
    assert account.status == SisAccount.Status.ACTIVE
    assert account.last_synced_at == NOW
    log = SisSyncLog.objects.get(sis_account=account)
    assert log.status == SisSyncLog.Status.SUCCESS
    assert log.items_created == 2


@freeze_time(NOW)
def test_sync_is_idempotent(sync, account, enrollment) -> None:
    sync(account)
    reminders = ScheduledReminder.objects.filter(user=account.user).count()

    second = sync(account)

    assert (second.items_created, second.items_updated, second.items_removed) == (0, 0, 0)
    assert Item.objects.filter(user=account.user).count() == 4
    assert LectureSchedule.objects.filter(user=account.user).count() == 1
    assert ScheduledReminder.objects.filter(user=account.user).count() == reminders


@freeze_time(NOW)
def test_existing_tutor_is_kept(sync, account, enrollment) -> None:
    enrollment.tutor_name = "From Moodle"
    enrollment.save()

    sync(account)

    enrollment.refresh_from_db()
    assert enrollment.tutor_name == "From Moodle"


@freeze_time(NOW)
def test_without_matching_enrollment_items_have_no_course(sync, account) -> None:
    sync(account)

    assert Item.objects.get(type=ItemType.EXAM, user=account.user).course_id is None
    assert LectureSchedule.objects.get(user=account.user).course_id is None


@freeze_time(NOW)
def test_moved_exam_is_updated_and_rescheduled(sync, account, sis) -> None:
    sync(account)
    item = Item.objects.get(type=ItemType.EXAM, user=account.user)
    sis.entries_by_user[USERNAME] = [
        *[e for e in sis.entries_by_user[USERNAME] if e.kind == "lecture"],
        exam(date(2026, 12, 22)),
    ]

    result = sync(account)

    assert result.items_updated == 1
    item.refresh_from_db()
    assert item.scheduled_at == datetime(2026, 12, 22, 7, 0, tzinfo=UTC)
    pending = ScheduledReminder.objects.filter(item=item, status=ScheduledReminder.Status.PENDING)
    assert pending.exists()
    assert all(r.send_at < item.scheduled_at for r in pending)


@freeze_time(NOW)
def test_removed_exam_and_timetable_are_removed(sync, account, sis) -> None:
    sync(account)
    item = Item.objects.get(type=ItemType.EXAM, user=account.user)
    sis.entries_by_user[USERNAME] = []

    result = sync(account)

    assert result.items_removed == 2
    item.refresh_from_db()
    assert item.deleted_at == NOW
    assert not ScheduledReminder.objects.filter(
        item=item, status=ScheduledReminder.Status.PENDING
    ).exists()
    assert not LectureSchedule.objects.filter(user=account.user).exists()
    assert not Item.objects.filter(user=account.user, type=ItemType.LECTURE).exists()


@freeze_time(NOW)
def test_changed_timetable_regenerates_occurrences(sync, account, sis) -> None:
    sync(account)
    sis.entries_by_user[USERNAME] = [
        lecture(date(2026, 10, 4)),
        lecture(date(2026, 10, 11)),
        lecture(date(2026, 10, 18)),
        lecture(date(2026, 10, 25)),
    ]

    result = sync(account)

    assert result.items_updated == 1
    schedule = LectureSchedule.objects.get(user=account.user)
    assert schedule.ends_on == date(2026, 10, 25)
    assert Item.objects.filter(lecture_schedule=schedule).count() == 4


@freeze_time(NOW)
def test_manual_items_are_untouched(sync, account, sis) -> None:
    manual = Item.objects.create(
        user=account.user,
        type=ItemType.EXAM,
        source=ItemSource.MANUAL,
        title="My exam",
        scheduled_at=NOW + timedelta(days=3),
    )
    sis.entries_by_user[USERNAME] = []

    sync(account)

    manual.refresh_from_db()
    assert manual.deleted_at is None


@freeze_time(NOW)
def test_invalid_password_marks_account_and_notifies_once(sync, account, sis, fake_clients) -> None:
    sis.valid_credentials[USERNAME] = "changed"

    first = sync(account)
    account.status = SisAccount.Status.ACTIVE  # e.g. a concurrent sync still saw it active
    second = sync(account)

    assert first.status == "failed"
    assert first.error == "invalid_credentials"
    assert second.status == "failed"
    account.refresh_from_db()
    assert account.status == SisAccount.Status.INVALID_CREDENTIALS
    notes = Notification.objects.filter(user=account.user, kind=Notification.Kind.SYSTEM)
    assert notes.count() == 1
    assert notes.get().title == "Reconnect the SIS"
    assert len(fake_clients.push.sent) == 1
    # Not synced any more until reconnected.
    assert sync(account).status == "skipped"


@freeze_time(NOW)
def test_unavailable_marks_error_and_recovers(sync, account, sis) -> None:
    sis.unavailable = True

    failed = sync(account)

    assert failed.status == "failed"
    account.refresh_from_db()
    assert account.status == SisAccount.Status.ERROR
    assert account.last_sync_error == "sis_unavailable"
    assert Notification.objects.filter(user=account.user).count() == 0

    sis.unavailable = False
    assert sync(account).status == "success"
    account.refresh_from_db()
    assert account.status == SisAccount.Status.ACTIVE
    assert account.last_sync_error == ""


@freeze_time(NOW)
def test_disabled_account_is_skipped(sync, account) -> None:
    account.status = SisAccount.Status.DISABLED
    account.save()

    assert sync(account).status == "skipped"
