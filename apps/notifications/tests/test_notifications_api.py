import pytest

from apps.notifications.models import Notification
from apps.notifications.tests.factories import NotificationFactory

pytestmark = pytest.mark.django_db


def test_list_is_paginated_newest_first(api, user) -> None:
    for _ in range(25):
        NotificationFactory(user=user)
    NotificationFactory()  # another user

    first = api.get("/api/v1/notifications")

    assert first.status_code == 200
    body = first.json()
    assert len(body["results"]) == 20
    assert body["next"]
    second = api.get(body["next"])
    assert len(second.json()["results"]) == 5
    item = body["results"][0]
    assert set(item) == {
        "id",
        "kind",
        "title",
        "body",
        "item_id",
        "report_id",
        "read_at",
        "created_at",
    }


def test_unread_count_and_mark_read(api, user) -> None:
    a = NotificationFactory(user=user)
    NotificationFactory(user=user)
    NotificationFactory(user=user)

    assert api.get("/api/v1/notifications/unread-count").json() == {"count": 3}

    assert (
        api.post("/api/v1/notifications/mark-read", {"ids": [str(a.id)]}, format="json").status_code
        == 204
    )
    assert api.get("/api/v1/notifications/unread-count").json() == {"count": 2}

    assert api.post("/api/v1/notifications/mark-read", {}, format="json").status_code == 204
    assert api.get("/api/v1/notifications/unread-count").json() == {"count": 0}


def test_mark_read_ignores_other_users(api) -> None:
    other = NotificationFactory()

    api.post("/api/v1/notifications/mark-read", {"ids": [str(other.id)]}, format="json")

    assert Notification.objects.get(pk=other.pk).read_at is None


def test_mark_read_validation(api) -> None:
    response = api.post("/api/v1/notifications/mark-read", {"ids": ["not-a-uuid"]}, format="json")

    assert response.status_code == 400


def test_notifications_require_auth(anon_api) -> None:
    assert anon_api.get("/api/v1/notifications").status_code == 401
    assert anon_api.get("/api/v1/notifications/unread-count").status_code == 401
