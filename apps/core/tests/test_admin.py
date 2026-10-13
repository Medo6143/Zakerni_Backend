"""Admin smoke tests: dashboard, reports inline reply, broadcast "Send now"."""

import pytest
from django.test import Client

from apps.accounts.tests.factories import UserFactory
from apps.broadcasts.models import Broadcast
from apps.moodle.models import MoodleAccount, SyncLog
from apps.notifications.models import Notification
from apps.notifications.tests.factories import DeviceFactory
from apps.support.models import Report, ReportReply
from apps.support.services.reports import create_report

pytestmark = pytest.mark.django_db


def test_template_context_copy_works() -> None:
    """Django < 5.2.8 broke Context copy on Python 3.14, which crashed admin lists."""
    from copy import copy

    from django.template.context import Context, RequestContext
    from django.test import RequestFactory

    context = Context({"a": 1})
    duplicate = copy(context)
    duplicate.push({"b": 2})
    assert "b" not in context and duplicate["a"] == 1
    assert copy(RequestContext(RequestFactory().get("/")))["True"] is True


@pytest.fixture
def admin_client() -> Client:
    admin = UserFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(admin)
    return client


def test_dashboard_renders_kpis_chart_and_failed_syncs(admin_client) -> None:
    account = MoodleAccount(user=UserFactory(), site_url="https://lms", moodle_user_id=1)
    account.set_token("t")
    account.save()
    from django.utils import timezone

    SyncLog.objects.create(
        moodle_account=account, started_at=timezone.now(), status="failed", error="invalidtoken"
    )

    response = admin_client.get("/admin/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Active devices" in content
    assert "invalidtoken" in content
    assert 'data-type="bar"' in content


def test_dashboard_in_arabic(admin_client) -> None:
    response = admin_client.get("/admin/", HTTP_ACCEPT_LANGUAGE="ar")

    assert response.status_code == 200
    assert "الأجهزة النشطة" in response.content.decode()


@pytest.mark.parametrize(
    "path",
    [
        "/admin/support/report/",
        "/admin/broadcasts/broadcast/",
        "/admin/broadcasts/broadcast/add/",
        "/admin/reminders/scheduledreminder/",
        "/admin/moodle/synclog/",
        "/admin/accounts/user/",
        "/admin/schedule/item/",
        "/admin/notifications/device/",
    ],
)
def test_admin_pages_render(admin_client, path) -> None:
    assert admin_client.get(path).status_code == 200


def test_report_inline_reply_pushes_and_status_changes(
    admin_client, fake_clients, monkeypatch, django_capture_on_commit_callbacks
) -> None:
    from apps.support.testing import FakeReplyBroadcaster
    from config import container

    broadcaster = FakeReplyBroadcaster()
    monkeypatch.setattr(container, "reply_broadcaster", lambda: broadcaster)
    student = UserFactory()
    DeviceFactory(user=student, fcm_token="student-token")
    report = create_report(student, category="login", description="help")
    url = f"/admin/support/report/{report.pk}/change/"
    page = admin_client.get(url)
    assert page.status_code == 200
    assert "/ws/v1/reports/" in page.content.decode()
    assert 'id="report-live-thread"' in page.content.decode()

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            url,
            {
                "status": "in_progress",
                # attachments inline
                "attachments-TOTAL_FORMS": "0",
                "attachments-INITIAL_FORMS": "0",
                # add-reply inline
                "replies-TOTAL_FORMS": "1",
                "replies-INITIAL_FORMS": "0",
                "replies-0-body": "We are on it",
            },
        )

    assert response.status_code == 302, response.content.decode()[:2000]
    report.refresh_from_db()
    assert report.status == "in_progress"
    reply = ReportReply.objects.get(report=report)
    assert reply.is_staff is True and reply.body == "We are on it"
    assert fake_clients.push.sent[0][0] == "student-token"
    assert Notification.objects.filter(user=student, kind="report_reply").count() == 1
    assert broadcaster.sent == [reply]


def test_report_status_action(admin_client) -> None:
    report = create_report(UserFactory(), category="login", description="help")

    admin_client.post(
        "/admin/support/report/",
        {"action": "mark_resolved", "_selected_action": [str(report.pk)]},
    )

    assert Report.objects.get(pk=report.pk).status == "resolved"


def test_broadcast_send_now_action(
    admin_client, fake_clients, django_capture_on_commit_callbacks
) -> None:
    DeviceFactory(user=UserFactory(language="en"))
    broadcast = Broadcast.objects.create(title_ar="ع", body_ar="ن", title_en="T", body_en="B")

    with django_capture_on_commit_callbacks(execute=True):
        admin_client.post(
            "/admin/broadcasts/broadcast/",
            {"action": "send_now", "_selected_action": [str(broadcast.pk)]},
        )

    broadcast.refresh_from_db()
    assert broadcast.status == Broadcast.Status.SENT
    assert broadcast.recipients_count == 1
    assert fake_clients.push.sent[0][1].title == "T"


def test_broadcast_detail_send_now(admin_client, django_capture_on_commit_callbacks) -> None:
    broadcast = Broadcast.objects.create(title_ar="ع", body_ar="ن", title_en="T", body_en="B")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.get(f"/admin/broadcasts/broadcast/{broadcast.pk}/send-now/")

    assert response.status_code == 302
    broadcast.refresh_from_db()
    assert broadcast.status == Broadcast.Status.SENT
