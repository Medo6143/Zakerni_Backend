"""``TelegramBotClient`` over the Telegram Bot HTTP API (httpx, 10s timeout)."""

from __future__ import annotations

import logging

import httpx
from django.conf import settings

from apps.notifications.protocols import BotSendResult

logger = logging.getLogger(__name__)

_RETRIABLE_STATUS = {429, 500, 502, 503, 504}


class HttpTelegramBotClient:
    def __init__(self, bot_token: str, timeout: float = 10.0) -> None:
        self._bot_token = bot_token
        self._timeout = timeout

    @classmethod
    def from_settings(cls) -> HttpTelegramBotClient:
        return cls(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            timeout=settings.TELEGRAM_HTTP_TIMEOUT_SECONDS,
        )

    def get_updates(self, offset: int, wait_seconds: int = 25) -> list[dict]:
        """Long-poll ``getUpdates`` (local development only; production uses the webhook)."""
        url = f"https://api.telegram.org/bot{self._bot_token}/getUpdates"
        try:
            response = httpx.post(
                url,
                json={"offset": offset, "timeout": wait_seconds, "allowed_updates": ["message"]},
                timeout=wait_seconds + self._timeout,
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Telegram getUpdates failed: %s", type(exc).__name__)
            return []
        if not data.get("ok"):
            logger.warning(
                "Telegram getUpdates rejected: %s", str(data.get("description", ""))[:200]
            )
            return []
        return list(data.get("result", []))

    def delete_webhook(self) -> bool:
        """``getUpdates`` is refused while a webhook is set."""
        url = f"https://api.telegram.org/bot{self._bot_token}/deleteWebhook"
        try:
            return bool(httpx.post(url, timeout=self._timeout).json().get("ok"))
        except (httpx.HTTPError, ValueError):
            return False

    def send_message(self, chat_id: int, text: str) -> BotSendResult:
        if not self._bot_token:
            return BotSendResult(ok=False, error="telegram_not_configured")
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            # Never log the URL: it contains the bot token.
            logger.warning("Telegram send failed: %s", type(exc).__name__)
            return BotSendResult(ok=False, retryable=True, error=type(exc).__name__)

        if response.status_code == 200:
            return BotSendResult(ok=True)
        description = ""
        try:
            description = str(response.json().get("description", ""))[:200]
        except ValueError:
            pass
        if response.status_code == 403:
            return BotSendResult(ok=False, blocked=True, error=description or "forbidden")
        if response.status_code == 400 and "chat not found" in description.lower():
            return BotSendResult(ok=False, blocked=True, error=description)
        return BotSendResult(
            ok=False,
            retryable=response.status_code in _RETRIABLE_STATUS,
            error=description or f"http_{response.status_code}",
        )
