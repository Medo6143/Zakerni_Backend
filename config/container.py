"""The only module that wires protocols to concrete implementations.

Services declare dependencies as ``typing.Protocol`` types; this module is
where we decide which concrete class satisfies each protocol at runtime.
Views, tasks and admin actions ask this module for ready-to-use services.
Tests swap the external clients (``moodle_client``, ``sis_client``, ``push_sender``,
``telegram_bot_client``) for fakes by monkeypatching these functions.
"""

from __future__ import annotations

from functools import lru_cache

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
from apps.support.integrations.realtime import ChannelsReplyBroadcaster
from apps.support.protocols import ReplyBroadcaster

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
    return ChannelsReplyBroadcaster()


# --- composed services -------------------------------------------------------------


def notification_channels() -> ChannelRegistry:
    return build_channel_registry(push_sender=push_sender(), telegram_bot=telegram_bot_client())


def reminder_scheduler() -> ReminderScheduler:
    return ReminderSchedulingService(channels=notification_channels())


def dispatch_due_reminders() -> DispatchDueReminders:
    return DispatchDueReminders(channels=notification_channels())


def sync_moodle_account() -> SyncMoodleAccount:
    channels = notification_channels()
    return SyncMoodleAccount(
        client=moodle_client(),
        scheduler=ReminderSchedulingService(channels=channels),
        channels=channels,
    )


def sync_moodle_account_with(client: MoodleDataClient) -> SyncMoodleAccount:
    """The Moodle sync over an already-fetched payload (device mode): same service,
    different client."""
    channels = notification_channels()
    return SyncMoodleAccount(
        client=client,
        scheduler=ReminderSchedulingService(channels=channels),
        channels=channels,
    )


def sync_sis_account_with(client: SisClient) -> SyncSisAccount:
    """The SIS sync over an already-fetched schedule (device mode)."""
    channels = notification_channels()
    return SyncSisAccount(
        client=client,
        scheduler=ReminderSchedulingService(channels=channels),
        channels=channels,
    )


def sync_sis_account() -> SyncSisAccount:
    channels = notification_channels()
    return SyncSisAccount(
        client=sis_client(),
        scheduler=ReminderSchedulingService(channels=channels),
        channels=channels,
    )
