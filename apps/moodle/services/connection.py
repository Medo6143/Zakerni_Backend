"""Connect / disconnect the university LMS (optional, done from Settings).

``connect_lms`` records the Moodle identity the phone verified (no token, no password ever
reaches the server). ``disconnect_lms`` removes the link and the Moodle-sourced data;
manual items, lectures and SIS data are kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.moodle.models import MoodleAccount
from apps.reminders.protocols import ReminderScheduler
from apps.schedule.models import Enrollment, Item, ItemSource

if TYPE_CHECKING:
    from apps.accounts.models import User


@dataclass(frozen=True)
class LmsConnectData:
    username: str
    moodle_user_id: int
    full_name: str
    email: str
    site_url: str


def connect_lms(user: User, data: LmsConnectData) -> MoodleAccount:
    with transaction.atomic():
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

        fields: list[str] = []
        if not user.full_name and data.full_name:
            user.full_name = data.full_name
            fields.append("full_name")
        if not user.email and data.email:
            user.email = data.email
            fields.append("email")
        if fields:
            user.save(update_fields=fields)
    return account


def disconnect_lms(user: User, *, scheduler: ReminderScheduler) -> None:
    """Delete the account, soft-delete Moodle items (cancelling their reminders) and
    deactivate Moodle enrollments. Manual items, lectures and SIS data are untouched."""
    now = timezone.now()
    with transaction.atomic():
        items = list(
            Item.objects.filter(user=user, source=ItemSource.MOODLE, deleted_at__isnull=True)
        )
        for item in items:
            item.deleted_at = now
            item.save(update_fields=["deleted_at", "updated_at"])
            scheduler.cancel_for_item(item)
        Enrollment.objects.filter(user=user, is_active=True).update(is_active=False, updated_at=now)
        MoodleAccount.objects.filter(user=user).delete()
