from io import StringIO

import httpx
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.notifications.integrations.telegram_client import HttpTelegramBotClient
from apps.notifications.management.commands.telegram_set_webhook import build_webhook_url

BOT_TOKEN = "123456:SECRET-BOT-TOKEN"


@pytest.mark.parametrize(
    "base",
    [
        "https://api.example.com",
        "api.example.com",
        "https://api.example.com/",
        "https://api.example.com/api/v1/telegram/webhook",
    ],
)
def test_build_webhook_url(base) -> None:
    assert build_webhook_url(base) == "https://api.example.com/api/v1/telegram/webhook"


def test_build_webhook_url_rejects_http() -> None:
    with pytest.raises(CommandError):
        build_webhook_url("http://api.example.com")


def test_command_sets_webhook_without_printing_token(settings, monkeypatch) -> None:
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    calls: list = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return httpx.Response(200, json={"ok": True, "description": "Webhook was set"})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = StringIO()

    call_command("telegram_set_webhook", "--url", "https://api.example.com", stdout=out)

    url, payload = calls[0]
    assert url.endswith("/setWebhook")
    assert payload["url"] == "https://api.example.com/api/v1/telegram/webhook"
    assert payload["secret_token"] == "test-webhook-secret"
    assert BOT_TOKEN not in out.getvalue()
    assert "api.example.com/api/v1/telegram/webhook" in out.getvalue()


def test_command_failure_does_not_leak_token(settings, monkeypatch) -> None:
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN

    def boom(url, json, timeout):
        raise httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(httpx, "post", boom)

    with pytest.raises(CommandError) as excinfo:
        call_command("telegram_set_webhook", "--url", "https://api.example.com")
    assert BOT_TOKEN not in str(excinfo.value)


def test_command_requires_secret(settings) -> None:
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBHOOK_SECRET = ""
    with pytest.raises(CommandError):
        call_command("telegram_set_webhook", "--url", "https://api.example.com")


def test_set_webhook_without_token() -> None:
    assert HttpTelegramBotClient(bot_token="").set_webhook("https://x", "s") == (
        False,
        "telegram_not_configured",
    )
