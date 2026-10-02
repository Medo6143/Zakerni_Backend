from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.schedule.models import ItemStatus, ItemType
from apps.schedule.selectors import items_history
from apps.schedule.tests.factories import CourseFactory, ItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db


def _at(days: int) -> datetime:
    return NOW - timedelta(days=days)


def test_history_excludes_unset_other_users_and_deleted(user) -> None:
    kept = ItemFactory(user=user, status=ItemStatus.DONE, note="ok", scheduled_at=_at(1))
    ItemFactory(user=user, status="", scheduled_at=_at(1))
    ItemFactory(status=ItemStatus.DONE, scheduled_at=_at(1))
    ItemFactory(user=user, status=ItemStatus.DONE, deleted_at=timezone.now())

    assert list(items_history(user)) == [kept]


def test_history_orders_newest_first(user) -> None:
    old = ItemFactory(user=user, status=ItemStatus.ATTENDED, scheduled_at=_at(5))
    new = ItemFactory(user=user, status=ItemStatus.ATTENDED, scheduled_at=_at(1))

    assert list(items_history(user)) == [new, old]


def test_history_filters(user) -> None:
    course = CourseFactory()
    done = ItemFactory(user=user, status=ItemStatus.DONE, scheduled_at=_at(1))
    attended = ItemFactory(
        user=user,
        status=ItemStatus.ATTENDED,
        type=ItemType.LECTURE,
        course=course,
        scheduled_at=_at(2),
    )
    ItemFactory(user=user, status=ItemStatus.CANCELLED, scheduled_at=_at(3))

    assert list(items_history(user, statuses=["done", "attended"])) == [done, attended]
    assert list(items_history(user, item_type=ItemType.LECTURE)) == [attended]
    assert list(items_history(user, course_id=course.id)) == [attended]


def test_history_endpoint_paginates(api, user) -> None:
    for day in range(25):
        ItemFactory(user=user, status=ItemStatus.DONE, note=f"n{day}", scheduled_at=_at(day))

    first = api.get("/api/v1/items/history").json()
    assert len(first["results"]) == 20
    assert first["results"][0]["status"] == "done"
    assert first["results"][0]["note"] == "n0"
    assert first["next"]

    second = api.get(first["next"]).json()
    assert len(second["results"]) == 5
    assert second["next"] is None


def test_history_endpoint_status_filter(api, user) -> None:
    ItemFactory(user=user, status=ItemStatus.DONE, scheduled_at=_at(1))
    ItemFactory(user=user, status=ItemStatus.POSTPONED, scheduled_at=_at(2))

    body = api.get("/api/v1/items/history", {"status": "postponed"}).json()

    assert [i["status"] for i in body["results"]] == ["postponed"]


def test_history_endpoint_invalid_status(api) -> None:
    response = api.get("/api/v1/items/history", {"status": "done,bogus"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_history_requires_auth(anon_api) -> None:
    assert anon_api.get("/api/v1/items/history").status_code == 401
