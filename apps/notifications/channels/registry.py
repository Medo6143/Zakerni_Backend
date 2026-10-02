"""The one place that lists notification channels (Open/Closed).

Adding a channel (e.g. email) = a new class implementing ``NotificationChannel``
plus one line here. The dispatcher and scheduler iterate this mapping and
never branch on a channel code.
"""

from __future__ import annotations

from apps.notifications.channels.fcm import FcmChannel
from apps.notifications.channels.telegram import TelegramChannel
from apps.notifications.protocols import NotificationChannel, PushSender, TelegramBotClient

ChannelRegistry = dict[str, NotificationChannel]


def build_channel_registry(
    *, push_sender: PushSender, telegram_bot: TelegramBotClient
) -> ChannelRegistry:
    channels: list[NotificationChannel] = [
        FcmChannel(push_sender),
        TelegramChannel(telegram_bot),
    ]
    return {channel.code: channel for channel in channels}
