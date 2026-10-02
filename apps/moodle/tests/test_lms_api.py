import pytest

from apps.accounts.tests.factories import UserFactory
from apps.moodle.models import MoodleAccount, SyncLog
from apps.moodle.services.lms import plan_moodle_syncs
from apps.moodle.tasks import enqueue_moodle_syncs, sync_moodle_account_task


def _account(user, status=MoodleAccount.Status.ACTIVE) -> MoodleAccount:  # type: ignore[no-untyped-def]
    account = MoodleAccount(user=user, site_url="https://lms", moodle_user_id=5, status=status)
    account.set_token("tok")
    account.save()
    return account


@pytest.mark.django_db
def test_get_lms_status(api, user) -> None:
    _account(user)

    response = api.get("/api/v1/me/lms")

    assert response.status_code == 200
    assert response.json() == {"status": "active", "last_synced_at": None, "last_sync_error": ""}
    assert "token" not in str(response.json())


@pytest.mark.django_db
def test_get_lms_status_without_account_is_404(api) -> None:
    response = api.get("/api/v1/me/lms")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_lms_requires_auth(anon_api) -> None:
    assert anon_api.get("/api/v1/me/lms").status_code == 401
    assert anon_api.post("/api/v1/me/lms/sync").status_code == 401


@pytest.mark.django_db
def test_sync_now_runs_sync_and_is_throttled(api, user) -> None:
    account = _account(user)

    first = api.post("/api/v1/me/lms/sync")
    second = api.post("/api/v1/me/lms/sync")

    assert first.status_code == 202
    # Celery is eager in tests: the sync ran against the (empty) fake Moodle client.
    assert SyncLog.objects.filter(moodle_account=account, status="success").count() == 1
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "throttled"


@pytest.mark.django_db
def test_sync_now_with_expired_token_returns_401(api, user) -> None:
    _account(user, status=MoodleAccount.Status.EXPIRED)

    response = api.post("/api/v1/me/lms/sync")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "lms_token_expired"


@pytest.mark.django_db
def test_plan_and_enqueue_syncs_only_active_accounts() -> None:
    active = _account(UserFactory())
    _account(UserFactory(), status=MoodleAccount.Status.EXPIRED)

    plans = plan_moodle_syncs(spread_seconds=600)
    assert [p.account_id for p in plans] == [active.id]
    assert 0 <= plans[0].countdown <= 600

    assert enqueue_moodle_syncs() == 1
    assert SyncLog.objects.filter(moodle_account=active).count() == 1


@pytest.mark.django_db
def test_sync_task_with_missing_account() -> None:
    assert sync_moodle_account_task("00000000-0000-0000-0000-000000000000") == "missing"
