"""Telegram channel: plain-text message to the linked chat."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from apps.notifications.models import Channel
from apps.notifications.protocols import DeliveryResult, Message, TelegramBotClient
from apps.notifications.selectors import telegram_link_for_user
from apps.notifications.services.telegram_linking import unlink_telegram

if TYPE_CHECKING:
    from apps.accounts.models import User


def format_telegram_text(message: Message) -> str:
    body = message.long_body or message.body
    return f"{message.title}\n{body}" if body else message.title


class TelegramChannel:
    code: ClassVar[str] = Channel.TELEGRAM.value

    def __init__(self, bot_client: TelegramBotClient) -> None:
        self._bot = bot_client

    def is_available_for(self, user: User) -> bool:
        return telegram_link_for_user(user) is not None

    def send(self, user: User, message: Message) -> DeliveryResult:
        link = telegram_link_for_user(user)
        if link is None:
            return DeliveryResult.failure("telegram_not_linked")
        result = self._bot.send_message(link.chat_id, format_telegram_text(message))
        if result.ok:
            return DeliveryResult.success()
        if result.blocked:
            # 403: the user blocked the bot -> unlink and disable the Telegram channel.
            unlink_telegram(user)
            return DeliveryResult.failure(result.error or "telegram_blocked")
        return DeliveryResult.failure(result.error or "telegram_failed", retryable=result.retryable)
