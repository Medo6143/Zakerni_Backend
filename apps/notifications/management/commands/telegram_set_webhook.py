"""Production: register the bot webhook (run once after each deploy that changes the URL).

Calls ``setWebhook`` with ``https://<domain>/api/v1/telegram/webhook`` and
``TELEGRAM_WEBHOOK_SECRET`` as ``secret_token``. The bot token is never printed.
Do not run ``telegram_poll`` against the production bot: it deletes this webhook.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.integrations.telegram_client import HttpTelegramBotClient

WEBHOOK_PATH = "/api/v1/telegram/webhook"


def build_webhook_url(base: str) -> str:
    """Accepts ``https://host``, ``host`` or the full webhook URL."""
    base = base.strip().rstrip("/")
    if "://" not in base:
        base = f"https://{base}"
    parts = urlsplit(base)
    if parts.scheme != "https" or not parts.netloc:
        raise CommandError("The webhook URL must be an https URL (Telegram requires HTTPS).")
    return f"https://{parts.netloc}{WEBHOOK_PATH}"


class Command(BaseCommand):
    help = "Register the Telegram bot webhook (production)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--url",
            default="",
            help="Public base URL, e.g. https://api.example.com (default: RAILWAY_PUBLIC_DOMAIN).",
        )

    def handle(self, *args, **options) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set.")
        if not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError("TELEGRAM_WEBHOOK_SECRET is not set.")
        base = options["url"] or getattr(settings, "RAILWAY_PUBLIC_DOMAIN", "")
        if not base:
            raise CommandError("Pass --url https://<domain> (or set RAILWAY_PUBLIC_DOMAIN).")
        webhook_url = build_webhook_url(base)
        ok, description = HttpTelegramBotClient.from_settings().set_webhook(
            webhook_url, settings.TELEGRAM_WEBHOOK_SECRET
        )
        if not ok:
            raise CommandError(f"setWebhook failed: {description}")
        self.stdout.write(self.style.SUCCESS(f"Webhook set to {webhook_url}"))
