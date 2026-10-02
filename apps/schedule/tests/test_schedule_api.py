from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.notifications.tests.factories import DeviceFactory
from apps.schedule.models import Item
from apps.schedule.tests.factories import EnrollmentFactory, ItemFactory, MoodleQuizItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _frozen_clock():  # type: ignore[no-untyped-def]
    with freeze_time(NOW):
        yield


def _range(days: int = 30) -> dict[str, str]:
    return {
        "from": NOW.isoformat().replace("+00:00", "Z"),
        "to": (NOW + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
    }


def test_items_requires_auth(anon_api) -> None:
    assert anon_api.get("/api/v1/items", _range()).status_code == 401


def test_items_in_range(api, user, scheduler) -> None:
    DeviceFactory(user=user)
    course = EnrollmentFactory(user=user).course
    quiz = MoodleQuizItemFactory(
        user=user,
        course=course,
        scheduled_at=NOW + timedelta(days=3),
        available_from=NOW + timedelta(days=2),
    )
    scheduler.schedule_for_item(quiz)
    ItemFactory(user=user, scheduled_at=NOW + timedelta(days=90))  # out of range
    ItemFactory(scheduled_at=NOW + timedelta(days=3))  # another user

    response = api.get("/api/v1/items", _range())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert item["id"] == str(quiz.id)
    assert item["type"] == "quiz"
    assert item["course"] == {"id": str(course.id), "code": course.code, "name": course.name}
    assert item["is_editable"] is False
    assert item["reminders"]["offsets_minutes"] == [1440, 180]
    assert item["reminders"]["is_override"] is False
    assert item["reminders"]["next_at"] == "2026-12-03T10:00:00Z"
    assert item["lecture_schedule_id"] is None


def test_items_of_inactive_enrollments_are_hidden(api, user) -> None:
    active = EnrollmentFactory(user=user).course
    inactive = EnrollmentFactory(user=user, is_active=False).course
    shown = MoodleQuizItemFactory(user=user, course=active, scheduled_at=NOW + timedelta(days=2))
    MoodleQuizItemFactory(user=user, course=inactive, scheduled_at=NOW + timedelta(days=2))
    no_course = ItemFactory(user=user, course=None, scheduled_at=NOW + timedelta(days=3))

    response = api.get("/api/v1/items", _range())

    assert [i["id"] for i in response.json()] == [str(shown.id), str(no_course.id)]


def test_items_filter_by_type(api, user) -> None:
    MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=3))
    ItemFactory(user=user, scheduled_at=NOW + timedelta(days=3))

    response = api.get("/api/v1/items", {**_range(), "type": "exam"})

    assert [i["type"] for i in response.json()] == ["exam"]


@freeze_time(NOW)
def test_items_upcoming_from_now_filtered_by_type(api, user) -> None:
    MoodleQuizItemFactory(user=user, scheduled_at=NOW - timedelta(hours=1))  # past
    upcoming = MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=61))
    MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=63))  # beyond default
    ItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))  # exam

    response = api.get("/api/v1/items", {"from": "now", "type": "quiz"})

    assert response.status_code == 200
    assert [i["id"] for i in response.json()] == [str(upcoming.id)]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"from": "soon"},
        {"from": "2026-12-01T00:00:00Z", "to": "2027-03-01T00:00:00Z"},
        {"from": "2026-12-05T00:00:00Z", "to": "2026-12-01T00:00:00Z"},
    ],
)
def test_items_range_validation(api, params) -> None:
    response = api.get("/api/v1/items", params)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_create_exam_endpoint(api, user) -> None:
    response = api.post(
        "/api/v1/items",
        {
            "type": "exam",
            "title": "Final M110",
            "scheduled_at": "2026-12-20T08:00:00Z",
            "ends_at": "2026-12-20T10:00:00Z",
            "location": "Hall A",
        },
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "exam" and body["source"] == "manual"
    assert body["is_editable"] is True
    assert body["reminders"]["offsets_minutes"] == [4320, 1440]


def test_create_lecture_via_items_is_rejected(api) -> None:
    response = api.post(
        "/api/v1/items",
        {"type": "lecture", "title": "x", "scheduled_at": "2026-12-20T08:00:00Z"},
        format="json",
    )

    assert response.status_code == 400


def test_get_patch_delete_exam(api, user) -> None:
    item = ItemFactory(user=user)

    assert api.get(f"/api/v1/items/{item.id}").status_code == 200

    patched = api.patch(f"/api/v1/items/{item.id}", {"title": "Renamed"}, format="json")
    assert patched.status_code == 200
    assert patched.json()["title"] == "Renamed"

    assert api.delete(f"/api/v1/items/{item.id}").status_code == 204
    assert api.get(f"/api/v1/items/{item.id}").status_code == 404


def test_patch_moodle_item_is_rejected(api, user) -> None:
    item = MoodleQuizItemFactory(user=user)

    response = api.patch(f"/api/v1/items/{item.id}", {"title": "x"}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "item_not_editable"


def test_other_users_item_is_404(api) -> None:
    item = ItemFactory()

    assert api.get(f"/api/v1/items/{item.id}").status_code == 404


def test_mute_item(api, user) -> None:
    item = MoodleQuizItemFactory(user=user)

    response = api.patch(f"/api/v1/items/{item.id}/mute", {"is_muted": True}, format="json")

    assert response.status_code == 200
    assert response.json()["is_muted"] is True
    assert response.json()["reminders"]["next_at"] is None
    bad = api.patch(f"/api/v1/items/{item.id}/mute", {}, format="json")
    assert bad.status_code == 400


def test_lecture_crud(api, user) -> None:
    payload = {
        "title": "M110 lecture",
        "weekdays": [0, 2],
        "start_time": "18:00",
        "duration_minutes": 90,
        "location": "Room 5",
        "starts_on": "2026-11-01",
        "ends_on": "2027-01-31",
    }
    created = api.post("/api/v1/lectures", payload, format="json")
    assert created.status_code == 201
    body = created.json()
    assert body["start_time"] == "18:00"
    assert body["weekdays"] == [0, 2]
    schedule_id = body["id"]
    assert Item.objects.filter(lecture_schedule_id=schedule_id).count() == 17

    listed = api.get("/api/v1/lectures")
    assert [s["id"] for s in listed.json()] == [schedule_id]

    patched = api.patch(f"/api/v1/lectures/{schedule_id}", {"weekdays": [3]}, format="json")
    assert patched.status_code == 200
    assert Item.objects.filter(lecture_schedule_id=schedule_id).count() == 9

    # A generated occurrence cannot be edited through /items
    occurrence = Item.objects.filter(lecture_schedule_id=schedule_id).first()
    response = api.patch(f"/api/v1/items/{occurrence.id}", {"title": "x"}, format="json")
    assert response.status_code == 400

    assert api.delete(f"/api/v1/lectures/{schedule_id}").status_code == 204
    assert Item.objects.filter(user=user).count() == 0


def test_lecture_validation_error(api) -> None:
    response = api.post(
        "/api/v1/lectures",
        {
            "title": "x",
            "weekdays": [],
            "start_time": "18:00",
            "duration_minutes": 90,
            "starts_on": "2026-11-01",
            "ends_on": "2026-10-01",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "weekdays" in response.json()["error"]["details"]


def test_courses_list_and_mute(api, user) -> None:
    enrollment = EnrollmentFactory(user=user)
    MoodleQuizItemFactory(user=user, course=enrollment.course)
    MoodleQuizItemFactory(user=user, course=enrollment.course, scheduled_at=NOW - timedelta(days=1))
    EnrollmentFactory(user=user, is_active=False)

    listed = api.get("/api/v1/courses")
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": str(enrollment.course.id),
            "code": enrollment.course.code,
            "name": enrollment.course.name,
            "is_muted": False,
            "upcoming_count": 1,
        }
    ]

    muted = api.patch(f"/api/v1/courses/{enrollment.course.id}", {"is_muted": True}, format="json")
    assert muted.status_code == 200
    assert muted.json()["is_muted"] is True


def test_mute_unknown_course_is_404(api) -> None:
    response = api.patch(
        "/api/v1/courses/00000000-0000-0000-0000-000000000000", {"is_muted": True}, format="json"
    )

    assert response.status_code == 404


def test_course_detail(api, user) -> None:
    from apps.schedule.models import LectureSchedule

    enrollment = EnrollmentFactory(user=user, group_name="28", tutor_name="Dr. Tutor")
    course = enrollment.course
    soon = MoodleQuizItemFactory(user=user, course=course, scheduled_at=NOW + timedelta(days=2))
    MoodleQuizItemFactory(user=user, course=course, scheduled_at=NOW + timedelta(days=40))
    MoodleQuizItemFactory(user=user, course=course, scheduled_at=NOW - timedelta(days=1))
    MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=2))  # other course
    LectureSchedule.objects.create(
        user=user,
        course=course,
        title="Lecture",
        weekdays=[5],
        start_time="18:00",
        duration_minutes=90,
        location="Hall 1",
        starts_on=NOW.date(),
        ends_on=(NOW + timedelta(days=60)).date(),
    )

    response = api.get(f"/api/v1/courses/{course.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["course"] == {"id": str(course.id), "code": course.code, "name": course.name}
    assert (body["is_muted"], body["group_name"], body["tutor_name"]) == (
        False,
        "28",
        "Dr. Tutor",
    )
    assert [i["id"] for i in body["upcoming_items"]] == [str(soon.id)]
    assert body["upcoming_items"][0]["reminders"]["offsets_minutes"] is not None
    [schedule] = body["lecture_schedules"]
    assert schedule["weekdays"] == [5]
    assert schedule["start_time"] == "18:00"
    assert schedule["duration_minutes"] == 90


def test_course_detail_inactive_or_foreign_is_404(api, user) -> None:
    inactive = EnrollmentFactory(user=user, is_active=False)
    foreign = EnrollmentFactory()

    assert api.get(f"/api/v1/courses/{inactive.course.id}").status_code == 404
    assert api.get(f"/api/v1/courses/{foreign.course.id}").status_code == 404


def test_items_filter_by_course(api, user) -> None:
    course = EnrollmentFactory(user=user).course
    mine = MoodleQuizItemFactory(user=user, course=course, scheduled_at=NOW + timedelta(days=1))
    MoodleQuizItemFactory(user=user, scheduled_at=NOW + timedelta(days=1))

    response = api.get("/api/v1/items", {**_range(), "course": str(course.id)})

    assert [i["id"] for i in response.json()] == [str(mine.id)]


def test_create_quiz_endpoint(api) -> None:
    response = api.post(
        "/api/v1/items",
        {
            "type": "quiz",
            "title": "Quiz 2",
            "scheduled_at": "2026-12-20T20:00:00Z",
            "available_from": "2026-12-20T08:00:00Z",
        },
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "quiz" and body["source"] == "manual"
    assert body["is_editable"] is True
    assert body["available_from"] == "2026-12-20T08:00:00Z"
    assert body["reminders"]["offsets_minutes"] == [1440, 180]
