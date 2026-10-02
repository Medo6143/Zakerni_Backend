"""Reminder rules and per-item overrides."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import NotFoundAppError, TelegramNotLinked, ValidationAppError
from apps.notifications.models import Channel
from apps.notifications.selectors import is_telegram_linked
from apps.reminders.defaults import (
    DEFAULT_RULES,
    MAX_OFFSETS,
    OFFSET_MAX_MINUTES,
    OFFSET_MIN_MINUTES,
)
from apps.reminders.models import ItemReminderOverride, ReminderRule

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.reminders.protocols import ReminderScheduler
    from apps.schedule.models import Item


def validate_offsets(offsets: Iterable[int]) -> list[int]:
    """1..5 offsets, each 5..20160 minutes, unique. Returned sorted, largest first."""
    values = list(offsets)
    errors: list[str] = []
    if not 1 <= len(values) <= MAX_OFFSETS:
        errors.append(str(_("Choose between 1 and 5 reminder times.")))
    if any(
        isinstance(v, bool)
        or not isinstance(v, int)
        or not OFFSET_MIN_MINUTES <= v <= OFFSET_MAX_MINUTES
        for v in values
    ):
        errors.append(str(_("Each reminder time must be between 5 minutes and 14 days before.")))
    if len(set(values)) != len(values):
        errors.append(str(_("Reminder times must be unique.")))
    if errors:
        raise ValidationAppError(details={"offsets_minutes": errors})
    return sorted(values, reverse=True)


def create_default_reminder_rules(user: User) -> list[ReminderRule]:
    """Idempotently create one rule per item type from ``DEFAULT_RULES``.

    Telegram is only enabled when the user already has a linked Telegram
    (``telegram_enabled`` requires a link); linking later turns it on where
    the default includes it (``enable_default_telegram_channels``).
    """
    linked = is_telegram_linked(user)
    rules: list[ReminderRule] = []
    for item_type, default in DEFAULT_RULES.items():
        rule, _created = ReminderRule.objects.get_or_create(
            user=user,
            item_type=item_type,
            defaults={
                "offsets_minutes": list(default.offsets),
                "push_enabled": Channel.PUSH.value in default.channels,
                "telegram_enabled": linked and Channel.TELEGRAM.value in default.channels,
            },
        )
        rules.append(rule)
    return rules


ensure_reminder_rules = create_default_reminder_rules


def update_reminder_rule(
    user: User,
    item_type: str,
    *,
    offsets_minutes: list[int],
    push_enabled: bool,
    telegram_enabled: bool,
    scheduler: ReminderScheduler,
) -> ReminderRule:
    if item_type not in DEFAULT_RULES:
        raise NotFoundAppError()
    offsets = validate_offsets(offsets_minutes)
    if telegram_enabled and not is_telegram_linked(user):
        raise TelegramNotLinked()

    ensure_reminder_rules(user)
    with transaction.atomic():
        rule = ReminderRule.objects.select_for_update().get(user=user, item_type=item_type)
        rule.offsets_minutes = offsets
        rule.push_enabled = push_enabled
        rule.telegram_enabled = telegram_enabled
        rule.save()
    scheduler.reschedule_for_user(user, item_type=item_type)
    return rule


def confirm_default_rules(user: User) -> None:
    """Onboarding: the user reviewed the default reminders and pressed Continue."""
    ensure_reminder_rules(user)
    if user.reminder_defaults_confirmed_at is None:
        user.reminder_defaults_confirmed_at = timezone.now()
        user.save(update_fields=["reminder_defaults_confirmed_at"])


def enable_default_telegram_channels(user: User) -> None:
    """After linking Telegram, enable it for every type whose default includes it."""
    ensure_reminder_rules(user)
    types = [t for t, d in DEFAULT_RULES.items() if Channel.TELEGRAM.value in d.channels]
    ReminderRule.objects.filter(user=user, item_type__in=types).update(
        telegram_enabled=True, updated_at=timezone.now()
    )


def set_item_override(
    item: Item, offsets_minutes: list[int], *, scheduler: ReminderScheduler
) -> ItemReminderOverride:
    offsets = validate_offsets(offsets_minutes)
    override, _created = ItemReminderOverride.objects.update_or_create(
        item=item, defaults={"offsets_minutes": offsets}
    )
    scheduler.schedule_for_item(item)
    return override


def clear_item_override(item: Item, *, scheduler: ReminderScheduler) -> bool:
    deleted, _unused = ItemReminderOverride.objects.filter(item=item).delete()
    scheduler.schedule_for_item(item)
    return deleted > 0
