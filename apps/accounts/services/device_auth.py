"""Device-bound login (device mode, docs/01 section 4.1).

The server cannot verify a student against Moodle (Moodle blocks the server's IPs; the
phone talks to Moodle itself), so an account is bound to a random secret generated on the
first device that claims the username. Only an HMAC of the secret is stored; later logins
must present the same secret. Nothing here calls Moodle and no Moodle token is stored.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services.auth import LoginResult
from apps.core.exceptions import DeviceMismatch, NotFoundAppError
from apps.moodle.models import MoodleAccount
from apps.reminders.services.rules import create_default_reminder_rules


@dataclass(frozen=True)
class DeviceLoginData:
    username: str
    full_name: str
    email: str
    moodle_user_id: int
    site_url: str
    device_secret: str


def hash_device_secret(secret: str) -> str:
    key = str(settings.DEVICE_SECRET_KEY).encode()
    return hmac.new(key, secret.encode(), hashlib.sha256).hexdigest()


def reset_device_binding(user: User) -> None:
    """Admin recovery: the next device that logs in claims the account again."""
    user.device_secret_hash = ""
    user.device_bound_at = None
    user.save(update_fields=["device_secret_hash", "device_bound_at"])


def login_with_device(data: DeviceLoginData) -> LoginResult:
    if settings.LMS_FETCH_MODE != "device":
        raise NotFoundAppError()
    presented = hash_device_secret(data.device_secret)

    with transaction.atomic():
        user, is_new = User.objects.get_or_create(
            moodle_username=data.username,
            defaults={"full_name": data.full_name, "email": data.email},
        )
        # Serialises two devices claiming the same username at once.
        locked = User.objects.select_for_update().get(pk=user.pk)
        if locked.device_secret_hash:
            if not hmac.compare_digest(locked.device_secret_hash, presented):
                raise DeviceMismatch()
        else:
            locked.device_secret_hash = presented
            locked.device_bound_at = timezone.now()
            locked.save(update_fields=["device_secret_hash", "device_bound_at"])
        user = locked
        if not is_new and (data.full_name or data.email):
            user.full_name = data.full_name or user.full_name
            user.email = data.email or user.email
            user.save(update_fields=["full_name", "email"])

        account, _created = MoodleAccount.objects.get_or_create(
            user=user,
            defaults={"site_url": data.site_url, "moodle_user_id": data.moodle_user_id},
        )
        account.site_url = data.site_url
        account.moodle_user_id = data.moodle_user_id
        account.status = MoodleAccount.Status.ACTIVE
        account.last_sync_error = ""
        account.token_encrypted = ""  # the token stays on the phone
        account.save()

        create_default_reminder_rules(user)

    return LoginResult(user=user, is_new=is_new)
