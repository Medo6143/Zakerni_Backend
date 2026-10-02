"""Telegram deep-link account linking (docs/01 section 4.5).

1. ``create_link_token`` -> ``https://t.me/<bot>?start=<token>`` (10 min TTL, single use).
2. The user presses Start; Telegram calls our webhook with ``/start <token>``.
3. ``handle_telegram_update`` validates the token, saves the chat id and replies
   in the user's language.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import TelegramLinkExpired
from apps.notifications.models import Channel, TelegramLink, TelegramLinkToken
from apps.notifications.protocols import TelegramBotClient

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.reminders.protocols import ReminderScheduler

TOKEN_LENGTH = 32

# Bot texts (plain text, no emoji). Rendered with translation.override(language).
BOT_TEXT_LINKED = _(
    "Your Telegram account is now linked to Zakerni. Your reminders will arrive here."
)
BOT_TEXT_LINK_INVALID = _(
    "This link has expired or was already used. Open the Zakerni app and tap "
    "Connect Telegram to get a new one."
)
BOT_TEXT_WELCOME = _(
    "Welcome to Zakerni. To get your reminders here, open the Zakerni app, go to "
    "Settings, then Telegram, and tap Connect Telegram."
)


@dataclass(frozen=True)
class LinkInvitation:
    url: str
    expires_at: datetime


def _generate_token() -> str:
    # token_urlsafe only uses [A-Za-z0-9_-], which Telegram accepts in start parameters.
    return secrets.token_urlsafe(TOKEN_LENGTH)[:TOKEN_LENGTH]


def create_link_token(user: User) -> LinkInvitation:
    ttl = timedelta(minutes=settings.TELEGRAM_LINK_TOKEN_TTL_MINUTES)
    token = TelegramLinkToken.objects.create(
        token=_generate_token(), user=user, expires_at=timezone.now() + ttl
    )
    url = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token.token}"
    return LinkInvitation(url=url, expires_at=token.expires_at)


def link_chat(token: str, *, chat_id: int, username: str = "") -> User:
    """Consume a one-time token and link the chat. Raises ``TelegramLinkExpired``
    for unknown, expired or already used tokens."""
    now = timezone.now()
    with transaction.atomic():
        link_token = (
            TelegramLinkToken.objects.select_for_update()
            .select_related("user")
            .filter(token=token)
            .first()
        )
        if link_token is None or link_token.used_at is not None or link_token.expires_at <= now:
            raise TelegramLinkExpired()
        link_token.used_at = now
        link_token.save(update_fields=["used_at", "updated_at"])

        user = link_token.user
        # One chat per account: a chat previously linked to another account moves here.
        TelegramLink.objects.filter(chat_id=chat_id).exclude(user=user).delete()
        TelegramLink.objects.update_or_create(
            user=user,
            defaults={"chat_id": chat_id, "username": username[:64], "linked_at": now},
        )
    return user


def unlink_telegram(user: User) -> bool:
    """Remove the link, turn Telegram off in every rule and cancel pending Telegram
    reminders (``telegram_enabled`` requires a linked Telegram)."""
    from apps.reminders.models import ReminderRule, ScheduledReminder

    with transaction.atomic():
        deleted, _unused = TelegramLink.objects.filter(user=user).delete()
        ReminderRule.objects.filter(user=user, telegram_enabled=True).update(
            telegram_enabled=False, updated_at=timezone.now()
        )
        ScheduledReminder.objects.filter(
            user=user,
            channel=Channel.TELEGRAM.value,
            status=ScheduledReminder.Status.PENDING,
        ).update(status=ScheduledReminder.Status.CANCELLED, updated_at=timezone.now())
    return deleted > 0


def _language_for_chat(from_user: dict[str, Any]) -> str:
    code = str(from_user.get("language_code") or "")
    return "en" if code.startswith("en") else "ar"


def _reply(bot: TelegramBotClient, chat_id: int, text: Any, language: str) -> None:
    with translation.override(language):
        bot.send_message(chat_id, str(text))


def handle_telegram_update(
    update: dict[str, Any],
    *,
    bot: TelegramBotClient,
    scheduler: ReminderScheduler,
) -> None:
    """Process one webhook update. Never raises for bad input (Telegram would retry)."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or "").strip()
    if not chat or chat.get("type") != "private" or not isinstance(chat.get("id"), int):
        return
    chat_id: int = chat["id"]
    from_user = message.get("from") or {}
    fallback_language = _language_for_chat(from_user)

    parts = text.split(maxsplit=1)
    if not parts or parts[0].split("@", 1)[0] != "/start":
        _reply(bot, chat_id, BOT_TEXT_WELCOME, fallback_language)
        return
    if len(parts) == 1:
        _reply(bot, chat_id, BOT_TEXT_WELCOME, fallback_language)
        return

    try:
        user = link_chat(
            parts[1].strip(), chat_id=chat_id, username=str(from_user.get("username") or "")
        )
    except TelegramLinkExpired:
        _reply(bot, chat_id, BOT_TEXT_LINK_INVALID, fallback_language)
        return

    from apps.reminders.services.rules import enable_default_telegram_channels

    # Telegram is now available: turn it on where the type default includes it,
    # then include it for upcoming items.
    enable_default_telegram_channels(user)
    _reply(bot, chat_id, BOT_TEXT_LINKED, user.language)
    scheduler.reschedule_for_user(user)
