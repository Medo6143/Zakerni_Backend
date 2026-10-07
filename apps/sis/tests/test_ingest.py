"""``POST /me/sis/ingest``: gated, runs the unchanged ``SyncSisAccount`` over the payload."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.schedule.models import Item, ItemSource, ItemType, LectureSchedule
from apps.schedule.tests.factories import CourseFactory, EnrollmentFactory
from apps.sis.integrations.fake_client import FakeSisClient
from apps.sis.models import SisAccount, SisSyncLog
from apps.sis.protocols import SisScheduleEntry
from apps.sis.services.account import plan_sis_syncs, request_sis_sync
from apps.sis.services.sync import SyncSisAccount
from apps.sis.tasks import enqueue_sis_syncs, sync_sis_account_task

URL = "/api/v1/me/sis/ingest"
# Real time: DRF throttles do not work under freezegun.
TODAY = datetime.now(UTC).date()


@pytest.fixture(autouse=True)
def _enabled(settings) -> None:  # type: ignore[no-untyped-def]
    settings.SIS_INGEST_ENABLED = True


def entries_body() -> dict:
    return {
        "entries": [
            {
                "kind": "lecture",
                "day": (TODAY + timedelta(days=3)).isoformat(),
                "course_code": "M110",
                "start_time": "10:00",
                "end_time": "12:00",
                "location_en": "Room 1",
                "lecturer_en": "Dr. T",
            },
            {
                "kind": "lecture",
                "day": (TODAY + timedelta(days=10)).isoformat(),
                "course_code": "M110",
                "start_time": "10:00:00",
                "end_time": "12:00:00",
                "location_en": "Room 1",
                "lecturer_en": "Dr. T",
            },
            {
                "kind": "exam",
                "day": (TODAY + timedelta(days=60)).isoformat(),
                "course_code": "M110",
                "start_time": "09:00",
                "end_time": None,
                "exam_name": "Final",
                "location_ar": "Hall",
            },
        ]
    }


def as_entries(body: dict) -> list[SisScheduleEntry]:
    out = []
    for e in body["entries"]:
        out.append(
            SisScheduleEntry(
                kind=e["kind"],
                day=date.fromisoformat(e["day"]),
                start_time=time.fromisoformat(e["start_time"]),
                end_time=time.fromisoformat(e["end_time"]) if e.get("end_time") else None,
                course_code=e["course_code"],
                location_en=e.get("location_en", ""),
                location_ar=e.get("location_ar", ""),
                lecturer_en=e.get("lecturer_en", ""),
                exam_name=e.get("exam_name", ""),
            )
        )
    return out


def snapshot(user) -> tuple:  # type: ignore[no-untyped-def]
    exams = sorted(
        (i.external_id, i.title, i.location, i.scheduled_at)
        for i in Item.objects.filter(user=user, source=ItemSource.SIS, type=ItemType.EXAM)
    )
    lectures = sorted(
        (s.external_id, s.start_time, s.location, s.starts_on)
        for s in LectureSchedule.objects.filter(user=user, source=ItemSource.SIS)
    )
    return exams, lectures


@pytest.mark.django_db
def test_ingest_gives_the_same_result_as_the_password_path(api, user, scheduler, channels) -> None:
    body = entries_body()
    other = UserFactory(language=user.language)
    fake = FakeSisClient()
    fake.add_user("2026123456", "pw", as_entries(body))
    old_account = SisAccount(user=other, username="2026123456")
    old_account.set_password("pw")
    old_account.save()
    SyncSisAccount(client=fake, scheduler=scheduler, channels=channels)(old_account)

    response = api.post(URL, body, format="json")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"
    assert result["items_created"] >= 2
    assert result["last_synced_at"] is not None
    assert snapshot(user) == snapshot(other)
    assert snapshot(user)[0] and snapshot(user)[1]
    account = SisAccount.objects.get(user=user)
    assert account.password_encrypted == ""
    assert SisSyncLog.objects.filter(sis_account=account, status="success").count() == 1


@pytest.mark.django_db
def test_ingest_links_course_and_never_calls_the_sis(api, user, fake_clients) -> None:
    fake_clients.sis.unavailable = True  # any server-side SIS call would fail
    course = CourseFactory(code="M110")
    EnrollmentFactory(user=user, course=course)

    response = api.post(URL, entries_body(), format="json")

    assert response.status_code == 200
    assert Item.objects.get(user=user, type=ItemType.EXAM).course_id == course.id


@pytest.mark.django_db
def test_ingest_removes_what_the_snapshot_no_longer_has(api, user) -> None:
    api.post(URL, entries_body(), format="json")
    from django.core.cache import cache

    cache.clear()

    body = {"entries": []}
    result = api.post(URL, body, format="json").json()

    assert result["items_removed"] >= 2
    assert Item.objects.get(user=user, type=ItemType.EXAM).deleted_at is not None
    assert not LectureSchedule.objects.filter(user=user, source=ItemSource.SIS).exists()


@pytest.mark.django_db
def test_disabled_returns_404_envelope(api, settings) -> None:
    settings.SIS_INGEST_ENABLED = False

    response = api.post(URL, entries_body(), format="json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert not SisAccount.objects.exists()


@pytest.mark.django_db
def test_requires_auth() -> None:
    assert APIClient().post(URL, entries_body(), format="json").status_code == 401


@pytest.mark.django_db
def test_throttled_to_one_per_minute(api) -> None:
    first = api.post(URL, {"entries": []}, format="json")
    second = api.post(URL, {"entries": []}, format="json")

    assert (first.status_code, second.status_code) == (200, 429)


@pytest.mark.django_db
def test_other_users_untouched(api, user) -> None:
    bystander = UserFactory()
    SisAccount.objects.create(user=bystander, username="x")

    api.post(URL, entries_body(), format="json")

    assert Item.objects.filter(user=bystander).count() == 0
    assert SisAccount.objects.get(user=bystander).last_synced_at is None


@pytest.mark.django_db
def test_invalid_credentials_status_is_reset_by_a_successful_ingest(api, user) -> None:
    SisAccount.objects.create(user=user, username="u", status=SisAccount.Status.INVALID_CREDENTIALS)

    api.post(URL, {"entries": []}, format="json")

    assert SisAccount.objects.get(user=user).status == SisAccount.Status.ACTIVE


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"entries": "x"},
        {"entries": [{}] * 2001},
        {
            "entries": [
                {"kind": "party", "day": "2026-10-04", "course_code": "M", "start_time": "10:00"}
            ]
        },
        {
            "entries": [
                {"kind": "exam", "day": "2026-13-45", "course_code": "M", "start_time": "10:00"}
            ]
        },
        {
            "entries": [
                {"kind": "exam", "day": "2001-01-01", "course_code": "M", "start_time": "10:00"}
            ]
        },
        {
            "entries": [
                {"kind": "exam", "day": "2099-01-01", "course_code": "M", "start_time": "10:00"}
            ]
        },
        {
            "entries": [
                {"kind": "exam", "day": "2026-10-04", "course_code": "", "start_time": "10:00"}
            ]
        },
        {
            "entries": [
                {
                    "kind": "exam",
                    "day": "2026-10-04",
                    "course_code": "M" * 65,
                    "start_time": "10:00",
                }
            ]
        },
        {
            "entries": [
                {"kind": "exam", "day": "2026-10-04", "course_code": "M", "start_time": "25:00"}
            ]
        },
        {
            "entries": [
                {
                    "kind": "exam",
                    "day": "2026-10-04",
                    "course_code": "M",
                    "start_time": "10:00",
                    "location_en": "L" * 256,
                }
            ]
        },
    ],
)
def test_bad_payloads_are_rejected(api, body) -> None:
    response = api.post(URL, body, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert not SisAccount.objects.exists()


@pytest.mark.django_db
def test_passwordless_accounts_are_skipped_by_periodic_and_manual_sync(user) -> None:
    device = SisAccount.objects.create(user=user, username="")
    other = UserFactory()
    with_password = SisAccount(user=other, username="u")
    with_password.set_password("pw")
    with_password.save()

    planned = plan_sis_syncs(spread_seconds=0)

    assert [p.account_id for p in planned] == [with_password.id]
    assert enqueue_sis_syncs() == 1
    assert sync_sis_account_task(str(device.id)) == "no_password"
    assert SisSyncLog.objects.filter(sis_account=device).count() == 0
    queued: list = []
    request_sis_sync(user, enqueue=lambda *a: queued.append(a))
    assert queued == []


@pytest.mark.django_db
def test_connect_flow_still_stores_password(api, fake_clients) -> None:
    fake_clients.sis.add_user("2026123456", "pw", [])

    response = api.post(
        "/api/v1/me/sis", {"username": "2026123456", "password": "pw"}, format="json"
    )

    assert response.status_code == 201
    assert SisAccount.objects.get().password_encrypted != ""
