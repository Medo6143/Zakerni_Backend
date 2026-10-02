"""Real-time report threads over Django Channels (docs/05, "Real-time report chat")."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

if TYPE_CHECKING:
    from apps.support.models import ReportReply

logger = logging.getLogger(__name__)

REPLY_CREATED = "reply.created"


def report_group(report_id: uuid.UUID | str) -> str:
    return f"report_{uuid.UUID(str(report_id)).hex}"


def reply_payload(reply: ReportReply) -> dict[str, Any]:
    """Exactly the reply shape of ``GET /reports/{id}`` (``ReportReplySerializer``)."""
    from apps.support.api.serializers import ReportReplySerializer

    return dict(ReportReplySerializer(reply).data)


class ChannelsReplyBroadcaster:
    def reply_created(self, reply: ReportReply) -> None:
        layer = get_channel_layer()
        if layer is None:
            return
        try:
            async_to_sync(layer.group_send)(
                report_group(reply.report_id),
                {"type": REPLY_CREATED, "reply": reply_payload(reply)},
            )
        except Exception:  # the reply is stored; a broken channel layer must not fail it
            logger.exception("Could not broadcast report reply %s", reply.pk)


@dataclass
class FakeReplyBroadcaster:
    """Records broadcasts (tests)."""

    sent: list[ReportReply] = field(default_factory=list)

    def reply_created(self, reply: ReportReply) -> None:
        self.sent.append(reply)
