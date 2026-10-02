"""Live report thread over WebSocket (docs/05, "Real-time report chat")."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.tests.factories import UserFactory
from apps.core.ws_auth import WebSocketAuthStack
from apps.notifications.models import Notification
from apps.notifications.tests.factories import DeviceFactory
from apps.support.models import Report, ReportReply
from apps.support.routing import websocket_urlpatterns

pytestmark = pytest.mark.django_db(transaction=True)

APP = WebSocketAuthStack(URLRouter(websocket_urlpatterns))


def _token(user: Any, *, expired: bool = False) -> str:
    token = AccessToken.for_user(user)
    if expired:
        token.set_exp(lifetime=-timedelta(minutes=1))
    return str(token)


def _path(report: Report, token: str | None = None) -> str:
    path = f"/ws/v1/reports/{report.pk}/"
    return f"{path}?token={token}" if token is not None else path


def _report(user: Any) -> Report:
    return Report.objects.create(user=user, category="other", description="It broke")


def _staff() -> Any:
    return UserFactory(is_staff=True)


async def _connect(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Any:
    communicator = WebsocketCommunicator(APP, path, headers=headers or [])
    connected, _ = await communicator.connect()
    assert connected
    return communicator


async def _close_code(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> int:
    communicator = await _connect(path, headers)
    output = await communicator.receive_output(timeout=1)
    await communicator.disconnect()
    assert output["type"] == "websocket.close"
    return output["code"]


def test_owner_connects_and_stranger_is_rejected() -> None:
    owner, stranger = UserFactory(), UserFactory()
    report = _report(owner)

    async def run() -> int:
        communicator = await _connect(_path(report, _token(owner)))
        assert await communicator.receive_nothing(timeout=0.1)
        await communicator.disconnect()
        return await _close_code(_path(report, _token(stranger)))

    assert async_to_sync(run)() == 4403


@pytest.mark.parametrize("token", [None, "not-a-jwt", "expired"])
def test_missing_invalid_or_expired_token_is_rejected(token: str | None) -> None:
    owner = UserFactory()
    report = _report(owner)
    raw = _token(owner, expired=True) if token == "expired" else token

    assert async_to_sync(_close_code)(_path(report, raw)) == 4401


def test_staff_reply_reaches_student_live_and_by_push() -> None:
    student, staff = UserFactory(), _staff()
    DeviceFactory(user=student)
    report = _report(student)

    async def run() -> tuple[dict, dict]:
        student_ws = await _connect(_path(report, _token(student)))
        staff_ws = await _connect(_path(report, _token(staff)))
        await staff_ws.send_json_to({"type": "message", "body": "  We are on it  "})
        received = await student_ws.receive_json_from(timeout=2)
        echoed = await staff_ws.receive_json_from(timeout=2)
        await student_ws.disconnect()
        await staff_ws.disconnect()
        return received, echoed

    received, echoed = async_to_sync(run)()

    reply = ReportReply.objects.get(report=report)
    assert received == echoed
    assert received == {
        "type": "reply.created",
        "reply": {
            "id": str(reply.pk),
            "body": "We are on it",
            "is_staff": True,
            "created_at": reply.created_at.isoformat().replace("+00:00", "Z"),
        },
    }
    assert Notification.objects.filter(user=student, kind="report_reply").exists()


def test_student_message_reaches_staff() -> None:
    student, staff = UserFactory(), _staff()
    report = _report(student)

    async def run() -> dict:
        staff_ws = await _connect(_path(report, _token(staff)))
        student_ws = await _connect(_path(report, _token(student)))
        await student_ws.send_json_to({"type": "message", "body": "Still broken"})
        received = await staff_ws.receive_json_from(timeout=2)
        await student_ws.disconnect()
        await staff_ws.disconnect()
        return received

    received = async_to_sync(run)()

    assert received["type"] == "reply.created"
    assert received["reply"]["body"] == "Still broken"
    assert received["reply"]["is_staff"] is False


def test_rest_reply_is_broadcast_with_the_detail_shape() -> None:
    student = UserFactory()
    report = _report(student)
    client = Client(headers={"authorization": f"Bearer {_token(student)}"})

    async def run() -> dict:
        ws = await _connect(_path(report, _token(student)))
        from asgiref.sync import sync_to_async

        await sync_to_async(client.post)(
            f"/api/v1/reports/{report.pk}/replies",
            {"body": "Via REST"},
            content_type="application/json",
        )
        received = await ws.receive_json_from(timeout=2)
        await ws.disconnect()
        return received

    received = async_to_sync(run)()

    detail = client.get(f"/api/v1/reports/{report.pk}").json()
    assert received == {"type": "reply.created", "reply": detail["replies"][0]}


def test_blank_message_returns_error_envelope() -> None:
    student = UserFactory()
    report = _report(student)

    async def run() -> list[dict]:
        ws = await _connect(_path(report, _token(student)))
        await ws.send_json_to({"type": "message", "body": "   "})
        blank = await ws.receive_json_from(timeout=2)
        await ws.send_json_to({"type": "typing"})
        unknown = await ws.receive_json_from(timeout=2)
        await ws.disconnect()
        return [blank, unknown]

    blank, unknown = async_to_sync(run)()

    assert blank["type"] == "error"
    assert blank["error"]["code"] == "validation_error"
    assert "body" in blank["error"]["details"]
    assert unknown["error"]["code"] == "validation_error"
    assert not ReportReply.objects.exists()


def test_admin_session_needs_a_same_host_origin() -> None:
    staff = _staff()
    report = _report(UserFactory())
    client = Client()
    client.force_login(staff)
    cookie = f"{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}"

    async def run() -> tuple[bool, int]:
        ok = await _connect(
            _path(report), [(b"cookie", cookie.encode()), (b"origin", b"http://testserver")]
        )
        joined = await ok.receive_nothing(timeout=0.1)
        await ok.disconnect()
        code = await _close_code(_path(report), [(b"cookie", cookie.encode())])  # no Origin
        return joined, code

    joined, code = async_to_sync(run)()

    assert joined is True
    assert code == 4401
