"""Test doubles for the support app."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.support.models import ReportReply


@dataclass
class FakeReplyBroadcaster:
    """Records broadcasts (tests)."""

    sent: list[ReportReply] = field(default_factory=list)

    def reply_created(self, reply: ReportReply) -> None:
        self.sent.append(reply)
