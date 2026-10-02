"""Profile update / account deletion use cases."""

from __future__ import annotations

from django.db import transaction

from apps.accounts.models import User


def update_profile(user: User, *, language: str | None = None, timezone: str | None = None) -> User:
    fields: list[str] = []
    if language is not None:
        user.language = language
        fields.append("language")
    if timezone is not None:
        user.timezone = timezone
        fields.append("timezone")
    if fields:
        user.save(update_fields=fields)
    return user


def delete_account(user: User) -> None:
    """Deletes the user and, by cascade, the Moodle account (token), the SIS
    account (encrypted password), enrollments,
    items, lecture schedules, reminder rules/overrides, scheduled reminders,
    devices, Telegram link/tokens and notification history.

    Reports and report replies are kept for admin statistics but anonymised
    (``user``/``author`` set to NULL by ``on_delete=SET_NULL``), per docs/04-erd.md.
    """
    with transaction.atomic():
        user.delete()
