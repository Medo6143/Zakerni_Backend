import io
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.tests.factories import UserFactory
from apps.core.exceptions import ValidationAppError
from apps.notifications.models import Notification
from apps.notifications.tests.factories import DeviceFactory
from apps.support.integrations.realtime import FakeReplyBroadcaster
from apps.support.models import Report, ReportReply
from apps.support.services import reports as report_services

pytestmark = pytest.mark.django_db


def _png(name: str = "shot.png", size: tuple[int, int] = (10, 10)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def test_categories_are_translated(api) -> None:
    en = api.get("/api/v1/reports/categories", HTTP_ACCEPT_LANGUAGE="en")
    ar = api.get("/api/v1/reports/categories", HTTP_ACCEPT_LANGUAGE="ar")

    assert en.status_code == 200
    assert [c["code"] for c in en.json()] == [
        "reminder_not_received",
        "wrong_date",
        "login",
        "telegram",
        "other",
    ]
    assert en.json()[0]["label"] == "Reminder not received"
    assert ar.json()[0]["label"] == "التذكير موصلش"


def test_create_report_multipart_with_images(api, user) -> None:
    response = api.post(
        "/api/v1/reports",
        {
            "category": "wrong_date",
            "description": "Quiz 2 shows the wrong time",
            "device_info": json.dumps({"os": "Android 14", "model": "Pixel"}),
            "app_version": "1.0.0",
            "attachments": [_png("a.png"), _png("b.png")],
        },
        format="multipart",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["category"] == "wrong_date"
    assert body["status"] == "new"
    assert body["status_label"] == "New"
    assert len(body["attachments"]) == 2
    assert body["attachments"][0].startswith("http://testserver/media/reports/")
    assert body["replies"] == []
    report = Report.objects.get(user=user)
    assert report.device_info == {"os": "Android 14", "model": "Pixel"}


def test_create_report_json_without_attachments(api) -> None:
    response = api.post(
        "/api/v1/reports",
        {"category": "other", "description": "Hello", "device_info": {"os": "iOS"}},
        format="json",
    )

    assert response.status_code == 201


def test_too_many_attachments(api) -> None:
    response = api.post(
        "/api/v1/reports",
        {
            "category": "other",
            "description": "x",
            "attachments": [_png(f"{i}.png") for i in range(4)],
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert "attachments" in response.json()["error"]["details"]


def test_non_image_attachment_is_rejected(api) -> None:
    fake = SimpleUploadedFile("notes.png", b"not an image", content_type="image/png")

    response = api.post(
        "/api/v1/reports",
        {"category": "other", "description": "x", "attachments": [fake]},
        format="multipart",
    )

    assert response.status_code == 400


def test_attachment_size_limit(user, settings) -> None:
    settings.REPORT_MAX_ATTACHMENT_BYTES = 50
    with pytest.raises(ValidationAppError) as exc:
        report_services.create_report(
            user, category="other", description="x", attachments=[_png(size=(200, 200))]
        )
    assert "attachments" in exc.value.details


def test_invalid_category(api) -> None:
    response = api.post("/api/v1/reports", {"category": "nope", "description": "x"}, format="json")

    assert response.status_code == 400


def test_list_detail_and_reply_only_own(api, user) -> None:
    mine = report_services.create_report(user, category="login", description="mine")
    other = report_services.create_report(UserFactory(), category="login", description="other")

    listed = api.get("/api/v1/reports").json()
    assert [r["id"] for r in listed] == [str(mine.id)]
    assert api.get(f"/api/v1/reports/{other.id}").status_code == 404

    reply = api.post(f"/api/v1/reports/{mine.id}/replies", {"body": "More info"}, format="json")
    assert reply.status_code == 201
    assert reply.json()["is_staff"] is False
    detail = api.get(f"/api/v1/reports/{mine.id}").json()
    assert [r["body"] for r in detail["replies"]] == ["More info"]
    assert (
        api.post(f"/api/v1/reports/{other.id}/replies", {"body": "x"}, format="json").status_code
        == 404
    )
    assert api.post(f"/api/v1/reports/{mine.id}/replies", {}, format="json").status_code == 400


def test_report_creation_is_throttled(api) -> None:
    for _ in range(10):
        assert (
            api.post(
                "/api/v1/reports", {"category": "other", "description": "x"}, format="json"
            ).status_code
            == 201
        )

    response = api.post("/api/v1/reports", {"category": "other", "description": "x"}, format="json")

    assert response.status_code == 429
    assert api.get("/api/v1/reports").status_code == 200


def test_staff_reply_pushes_to_student(user, channels, fake_clients) -> None:
    DeviceFactory(user=user, fcm_token="tok-student")
    staff = UserFactory(is_staff=True)
    report = report_services.create_report(user, category="login", description="help")

    reply = report_services.add_staff_reply(
        report, staff, "We fixed it", channels=channels, broadcaster=FakeReplyBroadcaster()
    )

    assert reply.is_staff is True
    token, message = fake_clients.push.sent[0]
    assert token == "tok-student"
    assert message.title == "رد جديد على بلاغك"
    assert message.body == "We fixed it"
    assert message.data["route"] == f"/reports/{report.id}"
    notification = Notification.objects.get(user=user)
    assert notification.kind == "report_reply" and notification.report == report
    assert fake_clients.bot.sent == []  # push only


def test_change_status(user) -> None:
    report = report_services.create_report(user, category="login", description="help")

    report_services.change_report_status(report, "resolved")

    assert Report.objects.get(pk=report.pk).status == "resolved"
    with pytest.raises(ValidationAppError):
        report_services.change_report_status(report, "bogus")


def test_account_deletion_anonymises_reports(api, user) -> None:
    report = report_services.create_report(user, category="login", description="help")
    report_services.add_user_reply(report, user, "follow-up", broadcaster=FakeReplyBroadcaster())

    assert api.delete("/api/v1/me").status_code == 204

    report.refresh_from_db()
    assert report.user is None
    assert ReportReply.objects.get(report=report).author is None
