"""Course announcements: ingest (upsert, notify, retention) and ``GET /announcements``."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.moodle.models import CourseAnnouncement, MoodleAccount
from apps.moodle.protocols import MoodleAnnouncement
from apps.moodle.services.announcements import announcement_text, ingest_announcements
from apps.notifications.channels.fake import FakePushChannel, FakeTelegramChannel
from apps.notifications.models import Notification
from apps.notifications.protocols import DeliveryResult
from apps.notifications.tests.factories import DeviceFactory
from apps.schedule.models import Course
from apps.schedule.tests.factories import CourseFactory, EnrollmentFactory, MoodleQuizItemFactory

URL = "/api/v1/me/lms/ingest"
LIST_URL = "/api/v1/announcements"
NOW = datetime.now(UTC).replace(microsecond=0)


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def ann(discussion_id: int = 1, **overrides) -> dict:  # type: ignore[no-untyped-def]
    body = {
        "moodle_course_id": 10,
        "forum_id": 5,
        "discussion_id": discussion_id,
        "group_id": 0,
        "subject": "Lecture moved",
        "message": "<p>Tomorrow &amp; later</p><p>Room B</p>",
        "author_name": "Dr. Tutor",
        "time_created": ts(NOW - timedelta(hours=2)),
        "time_modified": ts(NOW - timedelta(hours=1)),
        "pinned": False,
        "url": "https://lms/mod/forum/discuss.php?d=1",
    }
    body.update(overrides)
    return body


def dto(discussion_id: int = 1, **overrides) -> MoodleAnnouncement:  # type: ignore[no-untyped-def]
    values = ann(discussion_id, **overrides)
    return MoodleAnnouncement(**values)


@pytest.fixture
def course(user) -> Course:  # type: ignore[no-untyped-def]
    course = CourseFactory(moodle_course_id=10, code="M110")
    EnrollmentFactory(user=user, course=course)
    return course


@pytest.fixture
def account(user) -> MoodleAccount:  # type: ignore[no-untyped-def]
    DeviceFactory(user=user)
    return MoodleAccount.objects.create(user=user, site_url="https://lms", moodle_user_id=77)


@pytest.fixture
def push() -> FakePushChannel:
    return FakePushChannel()


@pytest.fixture
def telegram() -> FakeTelegramChannel:
    return FakeTelegramChannel()


@pytest.fixture
def channels(push, telegram):  # type: ignore[no-untyped-def]
    return {push.code: push, telegram.code: telegram}


def test_announcement_text_strips_html_and_keeps_paragraphs() -> None:
    text = announcement_text("<p>A &amp;   B</p><div>x<br/>y</div>  <b>z</b>")
    assert text == "A & B\nx\ny\nz"


@pytest.mark.django_db
def test_upsert_creates_then_updates_without_renotifying(user, course, channels) -> None:
    ingest_announcements(user, [dto(1)], channels=channels, now=NOW)
    row = CourseAnnouncement.objects.get()
    assert row.body == "Tomorrow & later\nRoom B"
    assert row.course_id == course.id
    assert row.notified_at is not None
    assert Notification.objects.filter(kind="announcement").count() == 1

    changed = dto(1, subject="Lecture cancelled", pinned=True, time_modified=ts(NOW))
    created = ingest_announcements(user, [changed], channels=channels, now=NOW)

    assert created == 0
    row.refresh_from_db()
    assert (row.subject, row.pinned, row.modified_at) == ("Lecture cancelled", True, NOW)
    assert CourseAnnouncement.objects.count() == 1
    assert Notification.objects.filter(kind="announcement").count() == 1


@pytest.mark.django_db
def test_teams_link_is_extracted(user, course, channels) -> None:
    message = '<a href="https://teams.microsoft.com/l/meetup-join/abc">join</a>'
    ingest_announcements(user, [dto(1, message=message)], channels=channels, now=NOW)
    assert CourseAnnouncement.objects.get().teams_url == (
        "https://teams.microsoft.com/l/meetup-join/abc"
    )


@pytest.mark.django_db
def test_unknown_course_is_skipped(user, course, channels) -> None:
    ingest_announcements(user, [dto(1, moodle_course_id=999)], channels=channels, now=NOW)
    assert CourseAnnouncement.objects.count() == 0


@pytest.mark.django_db
def test_not_a_snapshot_missing_posts_are_kept(user, course, channels) -> None:
    ingest_announcements(user, [dto(1)], channels=channels, now=NOW)
    ingest_announcements(user, [dto(2)], channels=channels, now=NOW)
    assert CourseAnnouncement.objects.count() == 2


@pytest.mark.django_db
def test_old_announcements_are_silent(user, course, channels, push) -> None:
    old = dto(
        1, time_created=ts(NOW - timedelta(days=10)), time_modified=ts(NOW - timedelta(days=9))
    )
    created = ingest_announcements(user, [old], channels=channels, now=NOW)
    assert created == 1
    assert CourseAnnouncement.objects.get().notified_at is None
    assert Notification.objects.count() == 0
    assert push.sent == []


@pytest.mark.django_db
def test_notification_content_and_channels(user, course, channels, push, telegram) -> None:
    user.language = "en"
    user.save()
    ingest_announcements(user, [dto(1)], channels=channels, now=NOW)
    note = Notification.objects.get()
    assert note.kind == "announcement"
    assert note.title == "M110: Lecture moved"
    assert len(push.sent) == 1 and len(telegram.sent) == 1
    assert push.sent[0][1].body == "Tomorrow & later Room B"
    assert "Room B" in push.sent[0][1].long_body


@pytest.mark.django_db
def test_notifications_are_capped_with_a_summary(user, course, channels) -> None:
    user.language = "en"
    user.save()
    posts = [dto(i, time_created=ts(NOW - timedelta(hours=i))) for i in range(1, 9)]
    ingest_announcements(user, posts, channels=channels, now=NOW)
    notes = Notification.objects.filter(kind="announcement")
    assert notes.count() == 6
    assert notes.filter(body="3 more announcements").count() == 1
    assert CourseAnnouncement.objects.filter(notified_at__isnull=False).count() == 8


@pytest.mark.django_db
def test_arabic_wrapper_is_translated(user, course, channels) -> None:
    user.language = "ar"
    user.save()
    posts = [dto(i, time_created=ts(NOW - timedelta(hours=i))) for i in range(1, 8)]
    ingest_announcements(user, posts, channels=channels, now=NOW)
    summary = Notification.objects.get(title="إعلانات المقررات")
    assert "2" in summary.body and "إعلانات" in summary.body


@pytest.mark.django_db
def test_failed_and_raising_channels_do_not_fail_the_ingest(user, course, telegram) -> None:
    class Exploding(FakePushChannel):
        def send(self, user, message):  # type: ignore[no-untyped-def]
            raise RuntimeError("down")

    telegram.queue_results(DeliveryResult.failure("blocked"))
    channels = {"push": Exploding(), "telegram": telegram}

    created = ingest_announcements(user, [dto(1), dto(2)], channels=channels, now=NOW)

    assert created == 2
    assert CourseAnnouncement.objects.filter(notified_at__isnull=False).count() == 2


@pytest.mark.django_db
def test_retention_deletes_posts_older_than_180_days(user, course, channels) -> None:
    old = CourseAnnouncement.objects.create(
        user=user,
        course=course,
        moodle_discussion_id=50,
        forum_id=5,
        subject="Old",
        posted_at=NOW - timedelta(days=181),
        modified_at=NOW - timedelta(days=181),
    )
    ingest_announcements(user, [dto(1)], channels=channels, now=NOW)
    assert not CourseAnnouncement.objects.filter(pk=old.pk).exists()
    assert CourseAnnouncement.objects.count() == 1


# --- API ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_ingest_with_only_announcements_is_valid_and_keeps_items(api, user, account, course):
    item = MoodleQuizItemFactory(user=user, course=course)

    response = api.post(URL, {"announcements": [ann(1)]}, format="json")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert CourseAnnouncement.objects.filter(user=user).count() == 1
    item.refresh_from_db()
    assert item.deleted_at is None
    assert Notification.objects.filter(user=user, kind="announcement").count() == 1


def test_ingest_validation() -> None:
    from apps.moodle.api.ingest_serializers import LmsIngestSerializer

    def valid(payload: dict) -> bool:
        return LmsIngestSerializer(data=payload).is_valid()

    assert valid({"announcements": [ann(1)]})
    for bad in (
        ann(1, message="a\x00b"),
        ann(1, time_modified=5),
        ann(1, subject="x" * 256),
        {**ann(1), "discussion_id": 0},
    ):
        assert not valid({"announcements": [bad]})
    assert not valid({"announcements": [ann(i + 1) for i in range(501)]})


@pytest.mark.django_db
def test_list_requires_auth(anon_api) -> None:
    assert anon_api.get(LIST_URL).status_code == 401


@pytest.mark.django_db
def test_list_is_isolated_filtered_and_paginated(api, user, course) -> None:
    other_course = CourseFactory(moodle_course_id=11, code="M111")
    other_user = UserFactory()
    for i in range(25):
        CourseAnnouncement.objects.create(
            user=user,
            course=course if i % 5 else other_course,
            moodle_discussion_id=i + 1,
            forum_id=5,
            subject=f"S{i}",
            body="b",
            posted_at=NOW - timedelta(hours=i),
            modified_at=NOW - timedelta(hours=i),
        )
    CourseAnnouncement.objects.create(
        user=other_user,
        course=course,
        moodle_discussion_id=1,
        forum_id=5,
        subject="Secret",
        posted_at=NOW,
        modified_at=NOW,
    )

    first = api.get(LIST_URL).json()
    assert len(first["results"]) == 20
    assert first["results"][0]["subject"] == "S0"
    assert set(first["results"][0]) == {
        "id",
        "course",
        "subject",
        "body",
        "author_name",
        "pinned",
        "posted_at",
        "modified_at",
        "url",
        "teams_url",
        "group_id",
    }
    assert first["results"][0]["course"]["code"] == "M111"
    second = api.get(first["next"]).json()
    assert len(second["results"]) == 5
    assert "Secret" not in {r["subject"] for r in first["results"] + second["results"]}

    filtered = api.get(LIST_URL, {"course": str(other_course.id)}).json()
    assert {r["subject"] for r in filtered["results"]} == {f"S{i}" for i in (0, 5, 10, 15, 20)}
    assert api.get(LIST_URL, {"course": "nope"}).status_code == 400
