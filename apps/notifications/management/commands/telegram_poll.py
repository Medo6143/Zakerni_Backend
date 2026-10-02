"""Local development: pull bot updates with getUpdates instead of receiving the webhook.

A local backend has no public HTTPS URL for Telegram to call, so this command polls
and hands every update to the same service the webhook view uses.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.integrations.telegram_client import HttpTelegramBotClient
from apps.notifications.services import telegram_linking
from config import container

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Poll Telegram for bot updates (development only; production uses the webhook)."

    def handle(self, *args, **options) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set.")
        client = HttpTelegramBotClient.from_settings()
        client.delete_webhook()
        self.stdout.write("Polling Telegram for updates. Ctrl+C to stop.")
        offset = 0
        while True:
            for update in client.get_updates(offset):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                try:
                    telegram_linking.handle_telegram_update(
                        update,
                        bot=container.telegram_bot_client(),
                        scheduler=container.reminder_scheduler(),
                    )
                except Exception:
                    logger.exception("Telegram update failed")
