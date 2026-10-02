"""In-memory fakes for the push and Telegram clients (tests / local demo).

Interchangeable with ``FirebasePushSender`` / ``HttpTelegramBotClient``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.notifications.protocols import BotSendResult, Message, PushResult


@dataclass
class FakePushSender:
    sent: list[tuple[str, Message]] = field(default_factory=list)
    invalid_tokens: set[str] = field(default_factory=set)
    retryable_failure: bool = False

    def send(self, token: str, message: Message) -> PushResult:
        if token in self.invalid_tokens:
            return PushResult(ok=False, invalid_token=True, error="UnregisteredError")
        if self.retryable_failure:
            return PushResult(ok=False, retryable=True, error="UnavailableError")
        self.sent.append((token, message))
        return PushResult(ok=True)


@dataclass
class FakeTelegramBotClient:
    sent: list[tuple[int, str]] = field(default_factory=list)
    blocked_chats: set[int] = field(default_factory=set)
    retryable_failure: bool = False

    def send_message(self, chat_id: int, text: str) -> BotSendResult:
        if chat_id in self.blocked_chats:
            return BotSendResult(
                ok=False, blocked=True, error="Forbidden: bot was blocked by the user"
            )
        if self.retryable_failure:
            return BotSendResult(ok=False, retryable=True, error="http_502")
        self.sent.append((chat_id, text))
        return BotSendResult(ok=True)
