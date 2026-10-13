"""Login-with-LMS use case (Phase 1).

Flow: Moodle token -> site info -> get_or_create user -> default reminder
rules -> enqueue a background sync. Depends only on the ``MoodleSiteClient``
/ ``MoodleAuthClient`` protocols (Dependency Inversion) so tests can supply
``FakeMoodleClient`` instead of hitting the network.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.accounts.models import User
from apps.moodle.models import MoodleAccount
from apps.moodle.protocols import MoodleAuthClient, MoodleSiteClient
from apps.reminders.services.rules import create_default_reminder_rules


@dataclass(frozen=True)
class LoginResult:
    user: User
    is_new: bool


@dataclass(frozen=True)
class LoginWithLms:
    auth_client: MoodleAuthClient
    data_client: MoodleSiteClient

    def __call__(self, username: str, password: str) -> LoginResult:
        # The password is used exactly once, here, to obtain an LMS token.
        # It must never be stored or logged past this call (CLAUDE.md #2).
        token = self.auth_client.get_token(username, password)
        site_info = self.data_client.site_info(token)

        with transaction.atomic():
            user, is_new = User.objects.get_or_create(
                moodle_username=username,
                defaults={
                    "full_name": site_info.full_name,
                    "email": site_info.email,
                },
            )
            if not is_new and (
                user.full_name != site_info.full_name or user.email != site_info.email
            ):
                user.full_name = site_info.full_name
                user.email = site_info.email or user.email
                user.save(update_fields=["full_name", "email"])

            account, _ = MoodleAccount.objects.get_or_create(
                user=user,
                defaults={
                    "site_url": site_info.site_url,
                    "moodle_user_id": site_info.moodle_user_id,
                    "token_encrypted": "",
                },
            )
            account.site_url = site_info.site_url or account.site_url
            account.moodle_user_id = site_info.moodle_user_id
            account.status = MoodleAccount.Status.ACTIVE
            account.last_sync_error = ""
            account.set_token(token)
            account.save()

            # Idempotent: creates the per-type rules for new users and fills in any
            # rule missing for existing ones (e.g. a type added later).
            create_default_reminder_rules(user)

        transaction.on_commit(lambda: _enqueue_sync(account.id))

        return LoginResult(user=user, is_new=is_new)


def _enqueue_sync(moodle_account_id) -> None:
    from apps.moodle.tasks import sync_moodle_account_task

    sync_moodle_account_task.delay(str(moodle_account_id))
