from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.accounts.tests.factories import UserFactory
from apps.moodle.integrations.fake_client import FakeMoodleClient
from apps.moodle.integrations.http_client import filter_current_courses
from apps.moodle.models import MoodleAccount, SyncLog
from apps.moodle.protocols import (
    MoodleAssignment,
    MoodleCalendarEvent,
    MoodleCourse,
    MoodleCourseMember,
    MoodleGroup,
    MoodleQuiz,
)
from apps.moodle.services.sync import SyncMoodleAccount
from apps.notifications.models import Notification
from apps.notifications.tests.factories import DeviceFactory
from apps.reminders.models import ScheduledReminder
from apps.schedule.models import Enrollment, Item, ItemType

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
TOKEN = "tok-sync"
MOODLE_USER_ID = 77


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


@pytest.fixture
def moodle() -> FakeMoodleClient:
    client = FakeMoodleClient()
    client.courses_by_user[MOODLE_USER_ID] = [
        MoodleCourse(moodle_course_id=10, code="M110", name="Programming"),
    ]
    client.quizzes_by_course[10] = [
        MoodleQuiz(
            moodle_course_id=10,
            instance_id=1,
            name="Quiz 1",
            time_open=ts(NOW + timedelta(days=4)),
            time_close=ts(NOW + timedelta(days=5)),
            url="https://lms/mod/quiz/view.php?id=11",
        ),
    ]
    client.assignments_by_course[10] = [
        MoodleAssignment(
            moodle_course_id=10,
            instance_id=2,
            name="TMA 1",
            due_date=ts(NOW + timedelta(days=10)),
            allow_submissions_from=ts(NOW - timedelta(days=5)),
        ),
    ]
    return client


@pytest.fixture
def account(db) -> MoodleAccount:
    user = UserFactory()
    DeviceFactory(user=user)
    account = MoodleAccount(user=user, site_url="https://lms", moodle_user_id=MOODLE_USER_ID)
    account.set_token(TOKEN)
    account.save()
    return account


@pytest.fixture
def sync(moodle, scheduler, channels) -> SyncMoodleAccount:
    return SyncMoodleAccount(client=moodle, scheduler=scheduler, channels=channels)


@freeze_time(NOW)
def test_new_items_are_created_and_scheduled(sync, account) -> None:
    result = sync(account)

    assert result.status == "success"
    assert result.items_created == 2
    quiz = Item.objects.get(user=account.user, type=ItemType.QUIZ)
    assert quiz.external_id == "1"
    assert quiz.scheduled_at == NOW + timedelta(days=5)
    assert quiz.available_from == NOW + timedelta(days=4)
    assert quiz.course.code == "M110"
    tma = Item.objects.get(user=account.user, type=ItemType.TMA)
    assert tma.available_from == NOW - timedelta(days=5)
    assert Enrollment.objects.filter(user=account.user, is_active=True).count() == 1
    # quiz: 1440, 180 via push (Telegram not linked)
    assert set(
        ScheduledReminder.objects.filter(item=quiz).values_list("offset_minutes", "channel")
    ) == {(1440, "push"), (180, "push")}
    log = SyncLog.objects.get(moodle_account=account)
    assert log.status == SyncLog.Status.SUCCESS
    assert log.items_created == 2
    account.refresh_from_db()
    assert account.last_synced_at == NOW


@freeze_time(NOW)
def test_sync_is_idempotent(sync, account) -> None:
    sync(account)
    second = sync(account)

    assert second.items_created == 0
    assert second.items_updated == 0
    assert Item.objects.filter(user=account.user).count() == 2
    assert ScheduledReminder.objects.filter(user=account.user).count() == 4


@freeze_time(NOW)
def test_changed_date_reschedules(sync, account, moodle) -> None:
    sync(account)
    quiz = Item.objects.get(user=account.user, type=ItemType.QUIZ)
    new_close = NOW + timedelta(days=7)
    moodle.quizzes_by_course[10] = [
        MoodleQuiz(
            moodle_course_id=10,
            instance_id=1,
            name="Quiz 1 (extended)",
            time_open=ts(NOW + timedelta(days=4)),
            time_close=ts(new_close),
        )
    ]

    result = sync(account)

    assert result.items_updated == 1
    quiz.refresh_from_db()
    assert quiz.title == "Quiz 1 (extended)"
    row = ScheduledReminder.objects.get(item=quiz, offset_minutes=1440)
    assert row.send_at == new_close - timedelta(minutes=1440)
    assert row.status == ScheduledReminder.Status.PENDING


@freeze_time(NOW)
def test_removed_items_are_soft_deleted_and_cancelled(sync, account, moodle) -> None:
    sync(account)
    moodle.quizzes_by_course[10] = []

    result = sync(account)

    assert result.items_removed == 1
    quiz = Item.objects.get(user=account.user, type=ItemType.QUIZ)
    assert quiz.deleted_at == NOW
    assert not ScheduledReminder.objects.filter(
        item=quiz, status=ScheduledReminder.Status.PENDING
    ).exists()
    assert ScheduledReminder.objects.filter(item=quiz, status="cancelled").count() == 2


@freeze_time(NOW)
def test_item_returning_is_revived(sync, account, moodle) -> None:
    sync(account)
    original = list(moodle.quizzes_by_course[10])
    moodle.quizzes_by_course[10] = []
    sync(account)
    moodle.quizzes_by_course[10] = original

    sync(account)

    quiz = Item.objects.get(user=account.user, type=ItemType.QUIZ)
    assert quiz.deleted_at is None
    assert ScheduledReminder.objects.filter(item=quiz, status="pending").count() == 2


@freeze_time(NOW)
def test_dropped_course_deactivates_enrollment(sync, account, moodle) -> None:
    sync(account)
    moodle.courses_by_user[MOODLE_USER_ID] = []

    sync(account)

    assert not Enrollment.objects.filter(user=account.user, is_active=True).exists()
    assert Item.objects.filter(user=account.user, deleted_at__isnull=True).count() == 0


@freeze_time(NOW)
def test_item_without_due_date_is_stored_but_not_scheduled(sync, account, moodle) -> None:
    moodle.assignments_by_course[10] = [
        MoodleAssignment(moodle_course_id=10, instance_id=3, name="Open TMA", due_date=None)
    ]

    sync(account)

    tma = Item.objects.get(user=account.user, type=ItemType.TMA)
    assert tma.scheduled_at is None
    assert not ScheduledReminder.objects.filter(item=tma).exists()


@freeze_time(NOW)
def test_expired_token_marks_account_and_notifies_once(sync, account, moodle, fake_clients) -> None:
    moodle.expire_token(TOKEN)

    first = sync(account)
    second = sync(account)

    assert first.status == "failed"
    assert first.error == "invalidtoken"
    assert second.status == "skipped"
    account.refresh_from_db()
    assert account.status == MoodleAccount.Status.EXPIRED
    assert SyncLog.objects.get(moodle_account=account).status == SyncLog.Status.FAILED
    assert Notification.objects.filter(user=account.user, kind="system").count() == 1
    assert len(fake_clients.push.sent) == 1
    # Arabic user -> Arabic text
    assert fake_clients.push.sent[0][1].body != "Sign in again to keep your reminders working."


@freeze_time(NOW)
def test_lms_unavailable_logs_failure_and_keeps_account_active(sync, account, moodle) -> None:
    moodle.unavailable = True

    result = sync(account)

    assert result.status == "failed"
    account.refresh_from_db()
    assert account.status == MoodleAccount.Status.ACTIVE
    assert account.last_sync_error == "lms_unavailable"
    assert not Item.objects.filter(user=account.user).exists()


# --- current term only + calendar lectures -------------------------------------------

TEAMS = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=x&amp;y=1"


def _lecture_event(event_id: int = 500, **overrides) -> MoodleCalendarEvent:
    values = {
        "event_id": event_id,
        "moodle_course_id": 10,
        "name": "M110 online lecture",
        "time_start": ts(NOW + timedelta(days=2)),
        "duration_seconds": 5400,
        "description": f'<p>Join <b>here</b>: <a href="{TEAMS}">Teams</a></p>',
        "url": "https://lms/calendar/view.php?view=day&time=1",
    }
    values.update(overrides)
    return MoodleCalendarEvent(**values)


@freeze_time(NOW)
def test_course_no_longer_current_is_deactivated_and_items_removed(sync, account, moodle) -> None:
    moodle.courses_by_user[MOODLE_USER_ID].append(
        MoodleCourse(moodle_course_id=20, code="OLD101", name="Old course")
    )
    moodle.quizzes_by_course[20] = [
        MoodleQuiz(
            moodle_course_id=20,
            instance_id=9,
            name="Old quiz",
            time_open=None,
            time_close=ts(NOW + timedelta(days=3)),
        )
    ]
    sync(account)
    old = Item.objects.get(user=account.user, external_id="9")
    assert ScheduledReminder.objects.filter(item=old, status="pending").exists()

    # Next term: Moodle no longer lists the old course as in progress.
    moodle.courses_by_user[MOODLE_USER_ID] = moodle.courses_by_user[MOODLE_USER_ID][:1]
    result = sync(account)

    old.refresh_from_db()
    assert result.items_removed == 1
    assert old.deleted_at is not None
    assert not ScheduledReminder.objects.filter(item=old, status="pending").exists()
    enrollment = Enrollment.objects.get(user=account.user, course__moodle_course_id=20)
    assert enrollment.is_active is False
    assert Enrollment.objects.get(user=account.user, course__moodle_course_id=10).is_active


def test_fallback_course_filter_keeps_only_current_courses() -> None:
    now = ts(NOW)
    courses = [
        {"id": 1, "startdate": now - 100, "enddate": now + 100},
        {"id": 2, "startdate": now - 100, "enddate": 0},
        {"id": 3, "startdate": now - 200, "enddate": now - 100},  # ended
        {"id": 4, "startdate": now + 100, "enddate": now + 200},  # future
        {"id": 5, "startdate": now - 100, "enddate": 0, "hidden": True},
        {"id": 6, "startdate": now - 100, "enddate": 0, "visible": 0},
    ]

    assert [c["id"] for c in filter_current_courses(courses, now)] == [1, 2]


@freeze_time(NOW)
def test_calendar_event_with_teams_link_becomes_lecture(sync, account, moodle) -> None:
    moodle.events_by_course[10] = [_lecture_event()]

    sync(account)

    lecture = Item.objects.get(user=account.user, type=ItemType.LECTURE)
    assert lecture.source == "moodle"
    assert lecture.external_id == "event:500"
    assert lecture.url == TEAMS.replace("&amp;", "&")
    assert lecture.scheduled_at == NOW + timedelta(days=2)
    assert lecture.ends_at == NOW + timedelta(days=2, minutes=90)
    assert lecture.description == "Join here: Teams"
    assert lecture.course.code == "M110"
    assert ScheduledReminder.objects.filter(item=lecture, status="pending").exists()


@freeze_time(NOW)
def test_calendar_event_without_teams_link_uses_event_url(sync, account, moodle) -> None:
    moodle.events_by_course[10] = [_lecture_event(description="<p>Room 3</p>")]

    sync(account)

    lecture = Item.objects.get(user=account.user, type=ItemType.LECTURE)
    assert lecture.url == "https://lms/calendar/view.php?view=day&time=1"


@freeze_time(NOW)
def test_removed_calendar_event_is_soft_deleted(sync, account, moodle) -> None:
    moodle.events_by_course[10] = [_lecture_event()]
    sync(account)
    lecture = Item.objects.get(user=account.user, type=ItemType.LECTURE)

    moodle.events_by_course[10] = []
    sync(account)

    lecture.refresh_from_db()
    assert lecture.deleted_at is not None
    assert not ScheduledReminder.objects.filter(item=lecture, status="pending").exists()


@freeze_time(NOW)
def test_past_lecture_outside_window_is_kept(sync, account, moodle) -> None:
    moodle.events_by_course[10] = [_lecture_event()]
    sync(account)
    lecture = Item.objects.get(user=account.user, type=ItemType.LECTURE)

    with freeze_time(NOW + timedelta(days=5)):
        sync(account)  # the event is now older than the window and not fetched

    lecture.refresh_from_db()
    assert lecture.deleted_at is None


@freeze_time(NOW)
def test_activity_calendar_events_are_ignored(sync, account, moodle) -> None:
    moodle.events_by_course[10] = [
        _lecture_event(event_id=600, name="Quiz 1 closes", module_name="quiz"),
        _lecture_event(event_id=601, name="TMA 1 due", module_name="assign"),
    ]

    sync(account)

    assert not Item.objects.filter(user=account.user, type=ItemType.LECTURE).exists()


@freeze_time(NOW)
def test_activity_from_earlier_term_is_skipped_and_later_removed(sync, account, moodle) -> None:
    # First sync: the course start date is unknown, so the old quiz is imported.
    moodle.quizzes_by_course[10].append(
        MoodleQuiz(
            moodle_course_id=10,
            instance_id=5,
            name="Last term quiz",
            time_open=None,
            time_close=ts(NOW - timedelta(days=200)),
        )
    )
    sync(account)
    old = Item.objects.get(user=account.user, external_id="5")
    assert old.deleted_at is None

    # The reused course shell now reports this term's start date.
    moodle.courses_by_user[MOODLE_USER_ID] = [
        MoodleCourse(
            moodle_course_id=10,
            code="M110",
            name="Programming",
            start_date=ts(NOW - timedelta(days=7)),
        )
    ]
    result = sync(account)

    old.refresh_from_db()
    assert result.items_removed == 1
    assert old.deleted_at is not None
    live = Item.objects.filter(user=account.user, deleted_at__isnull=True)
    assert set(live.values_list("external_id", flat=True)) == {"1", "2"}


@freeze_time(NOW)
def test_new_activity_before_course_start_is_never_created(sync, account, moodle) -> None:
    moodle.courses_by_user[MOODLE_USER_ID] = [
        MoodleCourse(
            moodle_course_id=10,
            code="M110",
            name="Programming",
            start_date=ts(NOW - timedelta(hours=12)),
        )
    ]
    moodle.events_by_course[10] = [
        _lecture_event(event_id=70, time_start=ts(NOW - timedelta(hours=20))),  # before start
        _lecture_event(event_id=71, time_start=ts(NOW + timedelta(days=2))),
    ]
    moodle.assignments_by_course[10].append(
        MoodleAssignment(
            moodle_course_id=10,
            instance_id=6,
            name="Summer TMA",
            due_date=ts(NOW - timedelta(days=30)),
        )
    )

    sync(account)

    assert not Item.objects.filter(user=account.user, external_id="6").exists()
    lectures = Item.objects.filter(user=account.user, type=ItemType.LECTURE)
    assert list(lectures.values_list("external_id", flat=True)) == ["event:71"]


# --- group and tutor -------------------------------------------------------------------


def _add_group(moodle: FakeMoodleClient) -> None:
    moodle.groups_by_course_user[(10, MOODLE_USER_ID)] = [MoodleGroup(group_id=5, name="28")]
    moodle.members_by_group[5] = [
        MoodleCourseMember(user_id=MOODLE_USER_ID, full_name="Me", roles=("student",)),
        MoodleCourseMember(user_id=90, full_name="Other Student", roles=("student",)),
        MoodleCourseMember(user_id=91, full_name="Dr. Tutor", roles=("teacher",)),
        MoodleCourseMember(user_id=92, full_name="No Role", roles=()),
    ]


@freeze_time(NOW)
def test_sync_stores_group_and_tutor(sync, moodle, account) -> None:
    _add_group(moodle)

    assert sync(account).status == "success"

    enrollment = Enrollment.objects.get(user=account.user)
    assert enrollment.group_name == "28"
    assert enrollment.tutor_name == "Dr. Tutor"


@freeze_time(NOW)
def test_denied_group_lookup_keeps_sync_green_and_blank_tutor(sync, moodle, account) -> None:
    moodle.groups_denied = True

    assert sync(account).status == "success"

    enrollment = Enrollment.objects.get(user=account.user)
    assert (enrollment.group_name, enrollment.tutor_name) == ("", "")


@freeze_time(NOW)
def test_failed_tutor_lookup_does_not_fail_sync_and_keeps_stored_tutor(
    sync, moodle, account
) -> None:
    _add_group(moodle)
    sync(account)

    moodle.groups_unavailable = True
    assert sync(account).status == "success"

    enrollment = Enrollment.objects.get(user=account.user)
    assert enrollment.tutor_name == "Dr. Tutor"
