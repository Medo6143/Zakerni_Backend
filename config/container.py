"""The only module that wires protocols to concrete implementations.

Services declare dependencies as ``typing.Protocol`` types; this module is
where we decide which concrete class satisfies each protocol at runtime.
Views, tasks and admin actions ask this module for ready-to-use services.
Tests swap the external clients (``moodle_client``, ``sis_client``, ``push_sender``,
``telegram_bot_client``) for fakes by monkeypatching these functions.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from apps.accounts.services.auth import LoginWithLms
from apps.moodle.integrations.http_client import HttpMoodleClient
from apps.moodle.protocols import MoodleDataClient
from apps.moodle.services.sync import SyncMoodleAccount
from apps.notifications.channels.registry import ChannelRegistry, build_channel_registry
from apps.notifications.integrations.fcm_sender import FirebasePushSender
from apps.notifications.integrations.telegram_client import HttpTelegramBotClient
from apps.notifications.protocols import PushSender, TelegramBotClient
from apps.reminders.protocols import ReminderScheduler
from apps.reminders.services.dispatch import DispatchDueReminders
from apps.reminders.services.scheduling import ReminderSchedulingService
from apps.sis.integrations.http_client import HttpSisClient
from apps.sis.protocols import SisClient
from apps.sis.services.sync import SyncSisAccount
from apps.support.api.serializers import ReportReplySerializer
from apps.support.integrations.realtime import ChannelsReplyBroadcaster
from apps.support.models import ReportReply
from apps.support.protocols import ReplyBroadcaster


def _reply_payload(reply: ReportReply) -> dict[str, Any]:
    """Exactly the reply shape of ``GET /reports/{id}``."""
    return dict(ReportReplySerializer(reply).data)


# --- external clients ----------------------------------------------------------------


def moodle_client() -> MoodleDataClient:
    return HttpMoodleClient.from_settings()


def sis_client() -> SisClient:
    return HttpSisClient.from_settings()


@lru_cache(maxsize=1)
def _firebase_sender() -> FirebasePushSender:
    # Cached: the Firebase app is initialised once per process.
    return FirebasePushSender.from_settings()


def push_sender() -> PushSender:
    return _firebase_sender()


def telegram_bot_client() -> TelegramBotClient:
    return HttpTelegramBotClient.from_settings()


def reply_broadcaster() -> ReplyBroadcaster:
    return ChannelsReplyBroadcaster(serialize=_reply_payload)


# --- composed services -------------------------------------------------------------


def notification_channels() -> ChannelRegistry:
    return build_channel_registry(push_sender=push_sender(), telegram_bot=telegram_bot_client())


def reminder_scheduler() -> ReminderScheduler:
    return ReminderSchedulingService(channels=notification_channels())


def dispatch_due_reminders() -> DispatchDueReminders:
    return DispatchDueReminders(channels=notification_channels())


def _sync_deps() -> dict[str, Any]:
    """Collaborators shared by every sync service: one registry, one scheduler."""
    channels = notification_channels()
    return {"scheduler": ReminderSchedulingService(channels=channels), "channels": channels}


def login_with_lms() -> LoginWithLms:
    client = HttpMoodleClient.from_settings()
    return LoginWithLms(auth_client=client, data_client=client)


def sync_moodle_account_with(client: MoodleDataClient) -> SyncMoodleAccount:
    """The Moodle sync over any data client (the server's own, or a phone payload)."""
    return SyncMoodleAccount(client=client, **_sync_deps())


def sync_moodle_account() -> SyncMoodleAccount:
    return sync_moodle_account_with(moodle_client())


def sync_sis_account_with(client: SisClient) -> SyncSisAccount:
    """The SIS sync over any SIS client (the server's own, or a phone payload)."""
    return SyncSisAccount(client=client, **_sync_deps())


def sync_sis_account() -> SyncSisAccount:
    return sync_sis_account_with(sis_client())
