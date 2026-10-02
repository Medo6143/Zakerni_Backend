"""Live report thread: ``ws/v1/reports/<report_id>/`` (docs/05, "Real-time report chat").

Thin like a view: authentication comes from ``apps.core.ws_auth``, reads from the
selector, writes through ``add_chat_message``. Broadcasting is done by the reply
service on commit, so REST and admin replies reach this group too.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils.translation import gettext as _

from apps.core.exceptions import ApplicationError, ValidationAppError
from apps.support.integrations.realtime import report_group
from apps.support.selectors import report_for_chat
from apps.support.services import reports as report_services

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403


class ReportChatConsumer(AsyncJsonWebsocketConsumer):
    group_name: str = ""

    async def connect(self) -> None:
        user = self.scope.get("user")
        # Accept first so the client receives the application close code.
        await self.accept()
        if user is None or not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        report_id: uuid.UUID = self.scope["url_route"]["kwargs"]["report_id"]
        self.report = await database_sync_to_async(report_for_chat)(user, report_id)
        if self.report is None:
            await self.close(code=CLOSE_FORBIDDEN)
            return
        self.group_name = report_group(report_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)

    async def disconnect(self, code: int) -> None:
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        if not self.group_name:
            return
        try:
            content = json.loads(text_data or "")
        except ValueError:
            await self._send_error(
                ValidationAppError(details={"detail": [str(_("Invalid JSON."))]})
            )
            return
        await self.receive_json(content)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if not isinstance(content, dict) or content.get("type") != "message":
            await self._send_error(
                ValidationAppError(details={"type": [str(_("Unknown message type."))]})
            )
            return
        try:
            await database_sync_to_async(self._post)(content.get("body"))
        except ApplicationError as exc:
            await self._send_error(exc)

    def _post(self, body: Any) -> None:
        from config import container

        report_services.add_chat_message(
            self.report,
            self.scope["user"],
            body if isinstance(body, str) else "",
            channels=container.notification_channels(),
            broadcaster=container.reply_broadcaster(),
        )

    async def _send_error(self, exc: ApplicationError) -> None:
        await self.send_json(
            {
                "type": "error",
                "error": {"code": exc.code, "message": str(exc.message), "details": exc.details},
            }
        )

    # group event "reply.created"
    async def reply_created(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "reply.created", "reply": event["reply"]})
