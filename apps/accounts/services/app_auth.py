"""App-account use cases: register, sign in, change password.

The app has its own accounts (student number + app password, hashed by Django). Connecting
the university is a separate optional step (``connect_lms``). Nothing here calls Moodle.
Sign-in answers one generic error for every failure (no user enumeration) and locks a
username out after repeated failures (cache-backed counter).
"""

from __future__ import annotations

import re
import secrets

from django.contrib.auth import password_validation
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.core.exceptions import (
    InvalidCredentials,
    TooManyAttempts,
    UsernameTaken,
    ValidationAppError,
)
from apps.reminders.services.rules import create_default_reminder_rules

USERNAME_RE = re.compile(r"^[a-z0-9]{3,32}$")
MAX_FAILED_ATTEMPTS = 10
LOCKOUT_SECONDS = 15 * 60

# A real hash so unknown users cost the same as wrong passwords.
_DUMMY_HASH = make_password("zakerni-dummy-password")


def normalize_username(raw: str) -> str:
    return raw.strip().lower()


def validate_new_password(password: str, *, user: User | None, field: str = "password") -> None:
    try:
        password_validation.validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValidationAppError(details={field: list(exc.messages)}) from exc


def register_user(*, username: str, password: str, language: str | None = None) -> User:
    username = normalize_username(username)
    if not USERNAME_RE.match(username):
        raise ValidationAppError(details={"username": [_("Use 3 to 32 letters or digits.")]})
    if User.objects.filter(moodle_username=username).exists():
        raise UsernameTaken()
    candidate = User(moodle_username=username)
    validate_new_password(password, user=candidate)
    if language:
        candidate.language = language
    candidate.set_password(password)
    try:
        with transaction.atomic():
            candidate.save()
            create_default_reminder_rules(candidate)
    except IntegrityError as exc:
        raise UsernameTaken() from exc
    return candidate


def _attempts_key(username: str) -> str:
    return f"signin-failures:{username}"


def sign_in(*, username: str, password: str) -> User:
    username = normalize_username(username)
    key = _attempts_key(username)
    if int(cache.get(key, 0)) >= MAX_FAILED_ATTEMPTS:
        raise TooManyAttempts()

    user = User.objects.filter(moodle_username=username).first()
    if user is not None and user.has_usable_password() and user.is_active:
        ok = check_password(password, user.password)
    else:
        check_password(password, _DUMMY_HASH)
        ok = False

    if not ok:
        cache.add(key, 0, LOCKOUT_SECONDS)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOCKOUT_SECONDS)
        raise InvalidCredentials()

    cache.delete(key)
    assert user is not None
    return user


def revoke_refresh_tokens(user: User) -> None:
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def change_password(user: User, *, old_password: str, new_password: str) -> None:
    if not user.check_password(old_password):
        raise ValidationAppError(details={"old_password": [_("Incorrect password.")]})
    validate_new_password(new_password, user=user, field="new_password")
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_refresh_tokens(user)


def set_temporary_password(user: User) -> str:
    """Staff recovery (there is no forgot-password flow): returns the new password once."""
    password = secrets.token_urlsafe(9)
    user.set_password(password)
    user.save(update_fields=["password"])
    revoke_refresh_tokens(user)
    cache.delete(_attempts_key(user.moodle_username))
    return password
