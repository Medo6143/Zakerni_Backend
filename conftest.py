"""Shared pytest fixtures.

External clients are always replaced by fakes (never mocked ad hoc): the
container's client factories are swapped for in-memory fakes for every test,
so nothing can reach Moodle, FCM or Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.moodle.integrations.fake_client import FakeMoodleClient
from apps.notifications.channels.registry import build_channel_registry
from apps.notifications.integrations.fakes import FakePushSender, FakeTelegramBotClient
from apps.reminders.services.scheduling import ReminderSchedulingService
from apps.sis.integrations.fake_client import FakeSisClient


@dataclass
class FakeClients:
    moodle: FakeMoodleClient
    push: FakePushSender
    bot: FakeTelegramBotClient
    sis: FakeSisClient


@pytest.fixture(autouse=True)
def fake_clients(monkeypatch: pytest.MonkeyPatch) -> FakeClients:
    from config import container

    clients = FakeClients(
        moodle=FakeMoodleClient(),
        push=FakePushSender(),
        bot=FakeTelegramBotClient(),
        sis=FakeSisClient(),
    )
    monkeypatch.setattr(container, "moodle_client", lambda: clients.moodle)
    monkeypatch.setattr(container, "push_sender", lambda: clients.push)
    monkeypatch.setattr(container, "telegram_bot_client", lambda: clients.bot)
    monkeypatch.setattr(container, "sis_client", lambda: clients.sis)
    return clients


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # Throttle counters live in the cache.
    cache.clear()


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def channels(fake_clients: FakeClients):  # type: ignore[no-untyped-def]
    """The real channel registry wired to the fake push/Telegram clients."""
    return build_channel_registry(push_sender=fake_clients.push, telegram_bot=fake_clients.bot)


@pytest.fixture
def scheduler(channels) -> ReminderSchedulingService:  # type: ignore[no-untyped-def]
    return ReminderSchedulingService(channels=channels)


@pytest.fixture
def user(db):  # type: ignore[no-untyped-def]
    from apps.accounts.tests.factories import UserFactory

    return UserFactory()


@pytest.fixture
def api(user) -> APIClient:  # type: ignore[no-untyped-def]
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def anon_api() -> APIClient:
    return APIClient()
