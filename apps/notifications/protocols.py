"""Ports for delivering notifications.

``NotificationChannel`` is what the dispatcher talks to (Open/Closed: a new
channel is a new class, the dispatcher never changes). ``PushSender`` and
``TelegramBotClient`` are the external clients behind the FCM and Telegram
channels (Dependency Inversion: channels never import firebase-admin or httpx).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol

if TYPE_CHECKING:
    from apps.accounts.models import User


@dataclass(frozen=True)
class Message:
    """A rendered, already-translated notification.

    ``body`` stays short (push). ``long_body`` is optional multi-line text
    (location, tutor, join link) for channels without a length budget, such as
    Telegram; they fall back to ``body`` when it is empty."""

    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    long_body: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    error: str = ""
    retryable: bool = False

    @classmethod
    def success(cls) -> DeliveryResult:
        return cls(ok=True)

    @classmethod
    def failure(cls, error: str, *, retryable: bool = False) -> DeliveryResult:
        return cls(ok=False, error=error, retryable=retryable)


class NotificationChannel(Protocol):
    """Contract shared by every channel (Liskov): ``send`` never raises for
    expected failures (invalid token, blocked bot, network error); it returns a
    failed ``DeliveryResult`` instead."""

    code: ClassVar[str]

    def is_available_for(self, user: User) -> bool: ...

    def send(self, user: User, message: Message) -> DeliveryResult: ...


# --- Push (FCM) ---------------------------------------------------------------


@dataclass(frozen=True)
class PushResult:
    ok: bool
    invalid_token: bool = False
    retryable: bool = False
    error: str = ""


class PushSender(Protocol):
    def send(self, token: str, message: Message) -> PushResult:
        """Send one push to one FCM registration token. Never raises."""
        ...


# --- Telegram -------------------------------------------------------------------


@dataclass(frozen=True)
class BotSendResult:
    ok: bool
    blocked: bool = False  # 403: the user blocked the bot / chat not found
    retryable: bool = False
    error: str = ""


class TelegramBotClient(Protocol):
    def send_message(self, chat_id: int, text: str) -> BotSendResult:
        """Send a plain-text message. Never raises."""
        ...
