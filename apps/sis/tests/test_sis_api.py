from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.schedule.models import Item, ItemSource, ItemType, LectureSchedule
from apps.sis.models import SisAccount, SisSyncLog
from apps.sis.protocols import SisScheduleEntry
from apps.sis.services.account import plan_sis_syncs
from apps.sis.tasks import enqueue_sis_syncs, sync_sis_account_task

PASSWORD = "sis-pass"


def _future_exam() -> SisScheduleEntry:
    day = (timezone.now() + timedelta(days=30)).date()
    return SisScheduleEntry(
        kind="exam", day=day, start_time=time(9, 0), end_time=None, course_code="M110"
    )


def _account(user, status=SisAccount.Status.ACTIVE) -> SisAccount:  # type: ignore[no-untyped-def]
    account = SisAccount(user=user, username=user.moodle_username, status=status)
    account.set_password(PASSWORD)
    account.save()
    return account


@pytest.mark.django_db
def test_status_when_not_connected(api) -> None:
    response = api.get("/api/v1/me/sis")

    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "username": "",
        "status": None,
        "last_synced_at": None,
        "last_sync_error": "",
    }


@pytest.mark.django_db
def test_connect_stores_encrypted_password_and_syncs(api, user, fake_clients) -> None:
    fake_clients.sis.add_user("2026123456", PASSWORD, [_future_exam()])

    response = api.post(
        "/api/v1/me/sis",
        {"username": " 2026123456 ", "password": PASSWORD},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["connected"] is True
    assert body["username"] == "2026123456"
    assert body["status"] == "active"
    assert PASSWORD not in str(body)
    assert "password" not in body
    account = SisAccount.objects.get(user=user)
    assert account.password_encrypted != PASSWORD
    assert account.get_password() == PASSWORD
    # Celery is eager in tests: the first sync already ran.
    assert SisSyncLog.objects.filter(sis_account=account, status="success").count() == 1
    assert Item.objects.filter(user=user, source=ItemSource.SIS, type=ItemType.EXAM).count() == 1


@pytest.mark.django_db
def test_connect_with_wrong_password_stores_nothing(api, user, fake_clients) -> None:
    fake_clients.sis.add_user("2026123456", PASSWORD)

    response = api.post(
        "/api/v1/me/sis", {"username": "2026123456", "password": "wrong"}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "sis_invalid_credentials"
    assert not SisAccount.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_connect_when_sis_is_down(api, user, fake_clients) -> None:
    fake_clients.sis.unavailable = True

    response = api.post("/api/v1/me/sis", {"username": "u", "password": "p"}, format="json")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "sis_unavailable"
    assert not SisAccount.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_connect_validates_input(api) -> None:
    response = api.post("/api/v1/me/sis", {"username": ""}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_reconnect_after_invalid_credentials(api, user, fake_clients) -> None:
    _account(user, status=SisAccount.Status.INVALID_CREDENTIALS)
    fake_clients.sis.add_user(user.moodle_username, "new-pass")

    response = api.post(
        "/api/v1/me/sis", {"username": user.moodle_username, "password": "new-pass"}, format="json"
    )

    assert response.status_code == 201
    account = SisAccount.objects.get(user=user)
    assert account.status == SisAccount.Status.ACTIVE
    assert account.get_password() == "new-pass"


@pytest.mark.django_db
def test_disconnect_removes_account_and_future_sis_items(api, user, fake_clients) -> None:
    fake_clients.sis.add_user(user.moodle_username, PASSWORD, [_future_exam()])
    api.post(
        "/api/v1/me/sis", {"username": user.moodle_username, "password": PASSWORD}, format="json"
    )
    LectureSchedule.objects.create(
        user=user,
        source=ItemSource.SIS,
        external_id="x",
        title="M110",
        weekdays=[0],
        start_time=time(10, 0),
        duration_minutes=60,
        starts_on=date.today(),
        ends_on=date.today() + timedelta(days=30),
    )
    manual = Item.objects.create(
        user=user,
        type=ItemType.EXAM,
        source=ItemSource.MANUAL,
        title="Mine",
        scheduled_at=timezone.now() + timedelta(days=5),
    )

    response = api.delete("/api/v1/me/sis")

    assert response.status_code == 204
    assert not SisAccount.objects.filter(user=user).exists()
    assert not Item.objects.filter(
        user=user, source=ItemSource.SIS, deleted_at__isnull=True
    ).exists()
    assert not LectureSchedule.objects.filter(user=user, source=ItemSource.SIS).exists()
    manual.refresh_from_db()
    assert manual.deleted_at is None
    assert api.delete("/api/v1/me/sis").status_code == 404


@pytest.mark.django_db
def test_sync_now_is_throttled(api, user) -> None:
    account = _account(user)

    first = api.post("/api/v1/me/sis/sync")
    second = api.post("/api/v1/me/sis/sync")

    assert first.status_code == 202
    # The fake SIS does not know this user: the eager sync marked it invalid.
    assert SisSyncLog.objects.filter(sis_account=account).count() == 1
    assert second.status_code == 429


@pytest.mark.django_db
def test_sync_now_with_invalid_credentials(api, user) -> None:
    _account(user, status=SisAccount.Status.INVALID_CREDENTIALS)

    response = api.post("/api/v1/me/sis/sync")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "sis_invalid_credentials"


@pytest.mark.django_db
def test_sync_now_without_account(api) -> None:
    assert api.post("/api/v1/me/sis/sync").status_code == 404


@pytest.mark.django_db
def test_sis_requires_auth(anon_api) -> None:
    assert anon_api.get("/api/v1/me/sis").status_code == 401
    assert anon_api.post("/api/v1/me/sis", {}).status_code == 401
    assert anon_api.post("/api/v1/me/sis/sync").status_code == 401


@pytest.mark.django_db
def test_sis_lecture_schedule_is_read_only(api, user) -> None:
    schedule = LectureSchedule.objects.create(
        user=user,
        source=ItemSource.SIS,
        external_id="x",
        title="M110",
        weekdays=[0],
        start_time=time(10, 0),
        duration_minutes=60,
        starts_on=date.today(),
        ends_on=date.today() + timedelta(days=30),
    )

    patch = api.patch(f"/api/v1/lectures/{schedule.id}", {"title": "x"}, format="json")
    delete = api.delete(f"/api/v1/lectures/{schedule.id}")

    assert patch.status_code == 400
    assert patch.json()["error"]["code"] == "item_not_editable"
    assert delete.status_code == 400


@pytest.mark.django_db
def test_plan_and_enqueue_only_syncable_accounts(fake_clients) -> None:
    active = _account(UserFactory())
    errored = _account(UserFactory(), status=SisAccount.Status.ERROR)
    _account(UserFactory(), status=SisAccount.Status.INVALID_CREDENTIALS)
    _account(UserFactory(), status=SisAccount.Status.DISABLED)
    for account in (active, errored):
        fake_clients.sis.add_user(account.username, PASSWORD)

    plans = plan_sis_syncs(spread_seconds=600)
    assert {p.account_id for p in plans} == {active.id, errored.id}
    assert all(0 <= p.countdown <= 600 for p in plans)

    assert enqueue_sis_syncs() == 2
    assert SisSyncLog.objects.filter(status="success").count() == 2


@pytest.mark.django_db
def test_sync_task_is_idempotent_and_handles_missing(user, fake_clients) -> None:
    account = _account(user)
    fake_clients.sis.add_user(account.username, PASSWORD, [_future_exam()])

    assert sync_sis_account_task(str(account.id)) == "success"
    assert sync_sis_account_task(str(account.id)) == "success"
    assert Item.objects.filter(user=user, source=ItemSource.SIS).count() == 1
    assert sync_sis_account_task("00000000-0000-0000-0000-000000000000") == "missing"


@pytest.mark.django_db
def test_account_deletion_removes_sis_account(api, user) -> None:
    _account(user)

    assert api.delete("/api/v1/me").status_code == 204
    assert not SisAccount.objects.exists()
