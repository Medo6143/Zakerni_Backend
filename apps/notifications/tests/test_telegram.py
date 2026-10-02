from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.accounts.tests.factories import UserFactory
from apps.notifications.channels.telegram import TelegramChannel
from apps.notifications.integrations.fakes import FakeTelegramBotClient
from apps.notifications.models import TelegramLink, TelegramLinkToken
from apps.notifications.protocols import Message
from apps.notifications.services.cleanup import delete_expired_link_tokens
from apps.notifications.services.telegram_linking import create_link_token
from apps.notifications.tests.factories import TelegramLinkFactory
from apps.reminders.models import ReminderRule, ScheduledReminder
from apps.reminders.services.rules import create_default_reminder_rules
from apps.schedule.tests.factories import MoodleQuizItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
SECRET = "test-webhook-secret"
CHAT_ID = 424242
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _frozen_clock():  # type: ignore[no-untyped-def]
    with freeze_time(NOW):
        yield


def _update(text: str, *, chat_id: int = CHAT_ID, language: str = "en") -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "from": {"id": chat_id, "username": "mo_wael", "language_code": language},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def _post(anon_api, payload, secret=SECRET):  # type: ignore[no-untyped-def]
    headers = {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": secret} if secret is not None else {}
    return anon_api.post("/api/v1/telegram/webhook", payload, format="json", **headers)


def test_create_link_token(user) -> None:
    invitation = create_link_token(user)

    token = TelegramLinkToken.objects.get(user=user)
    assert invitation.url == f"https://t.me/ZakerniBot?start={token.token}"
    assert len(token.token) == 32
    assert invitation.expires_at == NOW + timedelta(minutes=10)


def test_link_endpoint(api) -> None:
    response = api.post("/api/v1/telegram/link")

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://t.me/ZakerniBot?start=")
    assert response.json()["expires_at"] == "2026-12-01T10:10:00Z"


def test_valid_token_links_and_replies_in_user_language(anon_api, fake_clients) -> None:
    user = UserFactory(language="ar")
    create_default_reminder_rules(user)
    invitation = create_link_token(user)
    token = invitation.url.rsplit("=", 1)[1]

    response = _post(anon_api, _update(f"/start {token}"))

    assert response.status_code == 200
    link = TelegramLink.objects.get(user=user)
    assert link.chat_id == CHAT_ID and link.username == "mo_wael"
    assert TelegramLinkToken.objects.get(token=token).used_at == NOW
    chat, text = fake_clients.bot.sent[-1]
    assert chat == CHAT_ID
    assert "تليجرام" in text
    # Telegram turned on for types whose default includes it
    assert set(
        ReminderRule.objects.filter(user=user, telegram_enabled=True).values_list(
            "item_type", flat=True
        )
    ) == {"quiz", "tma", "exam"}


def test_linking_schedules_telegram_reminders(anon_api) -> None:
    user = UserFactory()
    item = MoodleQuizItemFactory(user=user)
    token = create_link_token(user).url.rsplit("=", 1)[1]

    _post(anon_api, _update(f"/start {token}"))

    assert (
        ScheduledReminder.objects.filter(item=item, channel="telegram", status="pending").count()
        == 2
    )


def test_expired_token_is_rejected(anon_api, fake_clients) -> None:
    user = UserFactory()
    token = create_link_token(user).url.rsplit("=", 1)[1]

    with freeze_time(NOW + timedelta(minutes=11)):
        response = _post(anon_api, _update(f"/start {token}"))

    assert response.status_code == 200
    assert not TelegramLink.objects.filter(user=user).exists()
    assert "expired" in fake_clients.bot.sent[-1][1]


def test_reused_token_is_rejected(anon_api, fake_clients) -> None:
    user = UserFactory()
    token = create_link_token(user).url.rsplit("=", 1)[1]
    _post(anon_api, _update(f"/start {token}"))

    _post(anon_api, _update(f"/start {token}", chat_id=999))

    assert TelegramLink.objects.get(user=user).chat_id == CHAT_ID
    assert not TelegramLink.objects.filter(chat_id=999).exists()
    assert "already used" in fake_clients.bot.sent[-1][1]


def test_unknown_token_and_plain_start(anon_api, fake_clients) -> None:
    _post(anon_api, _update("/start nope"))
    assert "expired" in fake_clients.bot.sent[-1][1]

    _post(anon_api, _update("/start", language="ar"))
    assert "ذكّرني" in fake_clients.bot.sent[-1][1]

    _post(anon_api, _update("hello"))
    assert "Welcome" in fake_clients.bot.sent[-1][1]


def test_chat_moves_to_the_new_account(anon_api) -> None:
    old = TelegramLinkFactory(chat_id=CHAT_ID)
    user = UserFactory()
    token = create_link_token(user).url.rsplit("=", 1)[1]

    _post(anon_api, _update(f"/start {token}"))

    assert not TelegramLink.objects.filter(pk=old.pk).exists()
    assert TelegramLink.objects.get(chat_id=CHAT_ID).user == user


@pytest.mark.parametrize("secret", [None, "wrong"])
def test_webhook_rejects_bad_secret(anon_api, fake_clients, secret) -> None:
    response = _post(anon_api, _update("/start x"), secret=secret)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert fake_clients.bot.sent == []


def test_webhook_ignores_non_private_and_non_message_updates(anon_api, fake_clients) -> None:
    group = _update("/start x")
    group["message"]["chat"]["type"] = "group"

    assert _post(anon_api, group).status_code == 200
    assert _post(anon_api, {"update_id": 2, "edited_message": {}}).status_code == 200
    assert fake_clients.bot.sent == []


def test_status_and_unlink(api, user) -> None:
    assert api.get("/api/v1/telegram").json() == {
        "linked": False,
        "username": None,
        "linked_at": None,
    }
    TelegramLinkFactory(user=user, username="mo")
    create_default_reminder_rules(user)
    ReminderRule.objects.filter(user=user).update(telegram_enabled=True)

    status = api.get("/api/v1/telegram").json()
    assert status["linked"] is True and status["username"] == "mo"
    assert api.get("/api/v1/me").json()["telegram_linked"] is True

    assert api.delete("/api/v1/telegram").status_code == 204
    assert not TelegramLink.objects.filter(user=user).exists()
    assert not ReminderRule.objects.filter(user=user, telegram_enabled=True).exists()
    assert api.get("/api/v1/me").json()["telegram_linked"] is False


def test_blocked_bot_unlinks_and_disables_channel(user) -> None:
    link = TelegramLinkFactory(user=user)
    create_default_reminder_rules(user)
    ReminderRule.objects.filter(user=user).update(telegram_enabled=True)
    item = MoodleQuizItemFactory(user=user)
    pending = ScheduledReminder.objects.create(
        user=user,
        item=item,
        offset_minutes=180,
        channel="telegram",
        send_at=NOW + timedelta(hours=1),
    )
    channel = TelegramChannel(FakeTelegramBotClient(blocked_chats={link.chat_id}))

    result = channel.send(user, Message(title="T", body="B"))

    assert result.ok is False and result.retryable is False
    assert not TelegramLink.objects.filter(user=user).exists()
    assert not ReminderRule.objects.filter(user=user, telegram_enabled=True).exists()
    pending.refresh_from_db()
    assert pending.status == "cancelled"
    assert channel.is_available_for(user) is False


def test_telegram_channel_success_and_retryable(user) -> None:
    link = TelegramLinkFactory(user=user)
    bot = FakeTelegramBotClient()
    channel = TelegramChannel(bot)

    assert channel.send(user, Message(title="Title", body="Body")).ok
    assert bot.sent == [(link.chat_id, "Title\nBody")]

    bot.retryable_failure = True
    result = channel.send(user, Message(title="T", body="B"))
    assert result.ok is False and result.retryable is True


def test_http_bot_without_token_never_raises() -> None:
    from apps.notifications.integrations.telegram_client import HttpTelegramBotClient

    result = HttpTelegramBotClient(bot_token="").send_message(1, "x")

    assert result.ok is False and result.error == "telegram_not_configured"


def test_cleanup_deletes_expired_tokens(user) -> None:
    create_link_token(user)
    with freeze_time(NOW + timedelta(minutes=30)):
        create_link_token(user)
        assert delete_expired_link_tokens() == 1
    assert TelegramLinkToken.objects.count() == 1
