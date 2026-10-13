"""Real-time report threads over Django Channels (docs/05, "Real-time report chat")."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

if TYPE_CHECKING:
    from apps.support.models import ReportReply

logger = logging.getLogger(__name__)

REPLY_CREATED = "reply.created"


def report_group(report_id: uuid.UUID | str) -> str:
    return f"report_{uuid.UUID(str(report_id)).hex}"


class ChannelsReplyBroadcaster:
    """Publishes a reply to the report's channel group. ``serialize`` shapes the payload
    (the container passes the API serializer, keeping this layer free of API imports)."""

    def __init__(self, serialize: Callable[[ReportReply], dict[str, Any]]) -> None:
        self._serialize = serialize

    def reply_created(self, reply: ReportReply) -> None:
        layer = get_channel_layer()
        if layer is None:
            return
        try:
            async_to_sync(layer.group_send)(
                report_group(reply.report_id),
                {"type": REPLY_CREATED, "reply": self._serialize(reply)},
            )
        except Exception:  # the reply is stored; a broken channel layer must not fail it
            logger.exception("Could not broadcast report reply %s", reply.pk)
