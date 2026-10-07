"""``POST /me/lms/ingest``: the phone pushes what it fetched; the unchanged sync stores it."""

from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.moodle.integrations.fake_client import FakeMoodleClient
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
from apps.schedule.models import Course, Enrollment, Item

URL = "/api/v1/me/lms/ingest"
# Real time: DRF throttles do not work under freezegun.
NOW = datetime.now(UTC).replace(microsecond=0)
MOODLE_USER_ID = 77


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def fixtures() -> FakeMoodleClient:
    """The same Moodle data as the old fetch path, as a FakeMoodleClient."""
    client = FakeMoodleClient()
    client.courses_by_user[MOODLE_USER_ID] = [
        MoodleCourse(
            moodle_course_id=10, code="M110", name="Programming", start_date=ts(NOW) - 86400 * 30
        ),
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
        # Earlier term: dated before the course start, skipped by the sync.
        MoodleQuiz(
            moodle_course_id=10,
            instance_id=9,
            name="Old quiz",
            time_open=None,
            time_close=ts(NOW - timedelta(days=200)),
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
    client.events_by_course[10] = [
        MoodleCalendarEvent(
            event_id=5,
            moodle_course_id=10,
            name="Lecture 1",
            time_start=ts(NOW + timedelta(days=2)),
            duration_seconds=3600,
            description='<a href="https://teams.microsoft.com/l/meetup-join/abc">join</a>',
        ),
        MoodleCalendarEvent(
            event_id=6,
            moodle_course_id=10,
            name="Activity event",
            time_start=ts(NOW + timedelta(days=3)),
            module_name="quiz",
        ),
    ]
    client.groups_by_course_user[(10, MOODLE_USER_ID)] = [MoodleGroup(group_id=3, name="G3")]
    client.members_by_group[3] = [
        MoodleCourseMember(user_id=MOODLE_USER_ID, full_name="Me", roles=("student",)),
        MoodleCourseMember(user_id=500, full_name="Dr. Tutor", roles=("teacher",)),
    ]
    return client


def payload_from(client: FakeMoodleClient) -> dict:
    """The JSON body a phone would build from the same data."""
    courses = client.courses_by_user[MOODLE_USER_ID]
    return {
        "courses": [
            {
                "moodle_course_id": c.moodle_course_id,
                "code": c.code,
                "name": c.name,
                "start_date": c.start_date,
            }
            for c in courses
        ],
        "groups": [
            {"moodle_course_id": cid, "group_id": g.group_id, "name": g.name}
            for (cid, _uid), groups in client.groups_by_course_user.items()
            for g in groups
        ],
        "group_members": [
            {
                "group_id": gid,
                "user_id": m.user_id,
                "full_name": m.full_name,
                "roles": list(m.roles),
            }
            for gid, members in client.members_by_group.items()
            for m in members
        ],
        "quizzes": [
            {
                "moodle_course_id": q.moodle_course_id,
                "instance_id": q.instance_id,
                "name": q.name,
                "time_open": q.time_open,
                "time_close": q.time_close,
                "url": q.url,
            }
            for qs in client.quizzes_by_course.values()
            for q in qs
        ],
        "assignments": [
            {
                "moodle_course_id": a.moodle_course_id,
                "instance_id": a.instance_id,
                "name": a.name,
                "due_date": a.due_date,
                "url": a.url,
                "allow_submissions_from": a.allow_submissions_from,
            }
            for a_list in client.assignments_by_course.values()
            for a in a_list
        ],
        "calendar_events": [
            {
                "event_id": e.event_id,
                "moodle_course_id": e.moodle_course_id,
                "name": e.name,
                "time_start": e.time_start,
                "duration_seconds": e.duration_seconds,
                "description": e.description,
                "url": e.url,
                "module_name": e.module_name,
            }
            for es in client.events_by_course.values()
            for e in es
        ],
    }


def tokenless_account(user) -> MoodleAccount:  # type: ignore[no-untyped-def]
    return MoodleAccount.objects.create(
        user=user, site_url="https://lms", moodle_user_id=MOODLE_USER_ID
    )


def snapshot(user) -> list[tuple]:  # type: ignore[no-untyped-def]
    return sorted(
        (
            i.type,
            i.external_id,
            i.title,
            i.url,
            i.scheduled_at,
            i.available_from,
            i.ends_at,
            i.description,
            i.deleted_at is None,
        )
        for i in Item.objects.filter(user=user)
    )


@pytest.fixture
def account(user) -> MoodleAccount:  # type: ignore[no-untyped-def]
    DeviceFactory(user=user)
    return tokenless_account(user)


@pytest.mark.django_db
def test_ingest_produces_the_same_items_as_the_old_fetch_path(
    api, user, account, scheduler, channels
) -> None:
    # Old path: the sync fetches from a (fake) Moodle with a stored token.
    other = UserFactory()
    old_account = MoodleAccount(user=other, site_url="https://lms", moodle_user_id=MOODLE_USER_ID)
    old_account.set_token("tok")
    old_account.save()
    old = fixtures()
    SyncMoodleAccount(client=old, scheduler=scheduler, channels=channels)(old_account)

    response = api.post(URL, payload_from(old), format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["items_created"] == 3
    assert body["items_updated"] == body["items_removed"] == 0
    assert body["last_synced_at"] is not None
    assert snapshot(user) == snapshot(other)
    assert len(snapshot(user)) == 3
    enrollment = Enrollment.objects.get(user=user)
    assert (enrollment.group_name, enrollment.tutor_name) == ("G3", "Dr. Tutor")
    account.refresh_from_db()
    assert account.token_encrypted == "" and account.last_synced_at is not None
    assert SyncLog.objects.filter(moodle_account=account, status="success").count() == 1


@pytest.mark.django_db
def test_ingest_never_calls_moodle(api, account, fake_clients) -> None:
    fake_clients.moodle.unavailable = True  # any server-side call would fail

    response = api.post(URL, payload_from(fixtures()), format="json")

    assert response.status_code == 200
    assert response.json()["status"] == "success"


@pytest.mark.django_db
def test_second_ingest_updates_and_removes(api, user, account) -> None:
    api.post(URL, payload_from(fixtures()), format="json")
    changed = fixtures()
    changed.quizzes_by_course[10] = []
    changed.assignments_by_course[10][0] = MoodleAssignment(
        moodle_course_id=10, instance_id=2, name="TMA 1 renamed", due_date=ts(NOW) + 86400 * 11
    )
    cache_clear()

    body = api.post(URL, payload_from(changed), format="json").json()

    assert body["items_updated"] == 1
    assert body["items_removed"] == 1
    assert Item.objects.get(user=user, external_id="2").title == "TMA 1 renamed"
    assert Item.objects.get(user=user, external_id="1").deleted_at is not None


def cache_clear() -> None:
    from django.core.cache import cache

    cache.clear()


@pytest.mark.django_db
def test_other_users_are_untouched(api, user, account) -> None:
    bystander = UserFactory()
    bystander_account = tokenless_account(bystander)
    api.post(URL, payload_from(fixtures()), format="json")
    bystander_items = Item.objects.filter(user=bystander).count()

    assert bystander_items == 0
    assert Enrollment.objects.filter(user=bystander).count() == 0
    bystander_account.refresh_from_db()
    assert bystander_account.last_synced_at is None


@pytest.mark.django_db
def test_ingest_cannot_rename_a_shared_course(api, account) -> None:
    Course.objects.create(moodle_course_id=10, code="REAL", name="Real name")

    api.post(URL, payload_from(fixtures()), format="json")

    course = Course.objects.get(moodle_course_id=10)
    assert (course.code, course.name) == ("REAL", "Real name")
    assert Enrollment.objects.filter(course=course).count() == 1


@pytest.mark.django_db
def test_expired_flag_marks_account_and_notifies_once(api, user, account, fake_clients) -> None:
    first = api.post(URL, {"lms_status": "expired"}, format="json")
    cache_clear()
    second = api.post(URL, {"lms_status": "expired"}, format="json")

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "failed"
    account.refresh_from_db()
    assert account.status == MoodleAccount.Status.EXPIRED
    assert Notification.objects.filter(user=user).count() == 1
    assert len(fake_clients.push.sent) == 1


@pytest.mark.django_db
def test_expired_flag_with_data_skips_syncing(api, user, account) -> None:
    body = {**payload_from(fixtures()), "lms_status": "expired"}

    response = api.post(URL, body, format="json")

    assert response.json()["status"] == "failed"
    assert Item.objects.filter(user=user).count() == 0
    account.refresh_from_db()
    assert account.status == MoodleAccount.Status.EXPIRED


@pytest.mark.django_db
def test_ingest_with_data_reactivates_an_expired_account(api, user, account) -> None:
    account.status = MoodleAccount.Status.EXPIRED
    account.save()

    response = api.post(URL, payload_from(fixtures()), format="json")

    assert response.json()["status"] == "success"
    account.refresh_from_db()
    assert account.status == MoodleAccount.Status.ACTIVE


@pytest.mark.django_db
def test_empty_courses_list_is_a_valid_snapshot(api, account) -> None:
    response = api.post(URL, {"courses": []}, format="json")

    assert response.status_code == 200
    assert response.json()["status"] == "success"


@pytest.mark.django_db
def test_ingest_requires_auth() -> None:
    assert APIClient().post(URL, {"courses": []}, format="json").status_code == 401


@pytest.mark.django_db
def test_ingest_without_moodle_account_is_404(api) -> None:
    response = api.post(URL, {"courses": []}, format="json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_ingest_is_throttled_to_one_per_minute(api, account) -> None:
    first = api.post(URL, {"courses": []}, format="json")
    second = api.post(URL, {"courses": []}, format="json")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "throttled"


@pytest.mark.django_db
def test_ingest_daily_cap(api, account, monkeypatch) -> None:
    from apps.core.api.throttling import LmsIngestDailyThrottle, LmsIngestThrottle

    monkeypatch.setitem(LmsIngestThrottle.THROTTLE_RATES, "lms_ingest", "100/min")
    monkeypatch.setitem(LmsIngestDailyThrottle.THROTTLE_RATES, "lms_ingest_daily", "2/day")

    statuses = [api.post(URL, {"courses": []}, format="json").status_code for _ in range(3)]

    assert statuses == [200, 200, 429]


COURSE = {"moodle_course_id": 10, "code": "M110", "name": "Programming", "start_date": 0}
QUIZ = {"moodle_course_id": 10, "instance_id": 1, "name": "Q"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"unknown": []},
        {"courses": "nope"},
        {"courses": [COURSE] * 201},
        {"courses": [COURSE], "quizzes": [QUIZ] * 2001},
        {"courses": [COURSE], "assignments": [{**QUIZ}] * 2001},
        {"courses": [COURSE], "calendar_events": [{}] * 2001},
        {"courses": [{**COURSE, "name": "x" * 256}]},
        {"courses": [{**COURSE, "code": "x" * 65}]},
        {"courses": [{**COURSE, "name": "bad\x00name"}]},
        {"courses": [{**COURSE, "moodle_course_id": 0}]},
        {"courses": [{**COURSE, "start_date": 5}]},
        {"courses": [{**COURSE, "start_date": 4_000_000_000_000}]},
        {"courses": [COURSE], "quizzes": [{**QUIZ, "time_close": 1_000_000_000}]},
        {"courses": [COURSE], "quizzes": [{**QUIZ, "time_close": -1}]},
        {"courses": [COURSE], "quizzes": [{**QUIZ, "url": "u" * 501}]},
        {"courses": [COURSE], "quizzes": [{"moodle_course_id": 10, "name": "no instance"}]},
        {"quizzes": [QUIZ]},
        {
            "courses": [COURSE],
            "calendar_events": [
                {"event_id": 1, "moodle_course_id": 10, "name": "E", "time_start": 0}
            ],
        },
        {
            "courses": [COURSE],
            "calendar_events": [
                {
                    "event_id": 1,
                    "moodle_course_id": 10,
                    "name": "E",
                    "time_start": 1_800_000_000,
                    "description": "d" * 20001,
                }
            ],
        },
        {
            "courses": [COURSE],
            "group_members": [{"group_id": 1, "user_id": 2, "roles": ["r"] * 21}],
        },
        {"lms_status": "active"},
    ],
)
def test_bad_payloads_are_rejected(api, account, body) -> None:
    response = api.post(URL, body, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert Item.objects.count() == 0


@pytest.mark.django_db
def test_duplicate_entries_are_collapsed(api, user, account) -> None:
    body = {"courses": [COURSE, COURSE], "quizzes": [QUIZ | {"time_close": ts(NOW) + 86400}] * 2}

    response = api.post(URL, body, format="json")

    assert response.status_code == 200
    assert Item.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_tokenless_account_status_endpoint_works(api, account) -> None:
    response = api.get("/api/v1/me/lms")

    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.django_db
def test_periodic_task_skips_tokenless_accounts(user, account) -> None:
    from apps.moodle.services.lms import plan_moodle_syncs
    from apps.moodle.tasks import enqueue_moodle_syncs, sync_moodle_account_task

    with_token = UserFactory()
    token_account = MoodleAccount(user=with_token, site_url="https://lms", moodle_user_id=5)
    token_account.set_token("tok")
    token_account.save()

    planned = plan_moodle_syncs(spread_seconds=0)

    assert [p.account_id for p in planned] == [token_account.id]
    assert enqueue_moodle_syncs() == 1
    assert sync_moodle_account_task(str(account.id)) == "no_token"
    assert SyncLog.objects.filter(moodle_account=account).count() == 0


@pytest.mark.django_db
def test_sync_now_does_not_enqueue_for_tokenless_account(api, account) -> None:
    response = api.post("/api/v1/me/lms/sync")

    assert response.status_code == 202
    assert SyncLog.objects.filter(moodle_account=account).count() == 0
