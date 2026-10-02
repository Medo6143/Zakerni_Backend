"""Recording fake channels for tests (same contract as the real channels)."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, ClassVar

from apps.notifications.models import Channel
from apps.notifications.protocols import DeliveryResult, Message

if TYPE_CHECKING:
    from apps.accounts.models import User


class FakeChannel:
    code: ClassVar[str] = "fake"

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.sent: list[tuple[User, Message]] = []
        self._queued: deque[DeliveryResult] = deque()

    def queue_results(self, *results: DeliveryResult) -> None:
        """Next ``send`` calls return these results in order (then success)."""
        self._queued.extend(results)

    def is_available_for(self, user: User) -> bool:
        return self.available

    def send(self, user: User, message: Message) -> DeliveryResult:
        result = self._queued.popleft() if self._queued else DeliveryResult.success()
        if result.ok:
            self.sent.append((user, message))
        return result


class FakePushChannel(FakeChannel):
    code: ClassVar[str] = Channel.PUSH.value


class FakeTelegramChannel(FakeChannel):
    code: ClassVar[str] = Channel.TELEGRAM.value
