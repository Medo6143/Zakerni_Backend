"""Ports used by the support use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apps.support.models import ReportReply


class ReplyBroadcaster(Protocol):
    def reply_created(self, reply: ReportReply) -> None:
        """Deliver a new reply to everyone connected to its report thread (WebSocket).

        Called after the transaction commits. Must not raise for delivery failures:
        the reply is already stored and the push notification still goes out."""
        ...
