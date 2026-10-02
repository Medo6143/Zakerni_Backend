import pytest
from django.db import transaction

from apps.accounts.tests.factories import UserFactory
from apps.broadcasts.models import Broadcast
from apps.broadcasts.selectors import estimated_recipients
from apps.broadcasts.services.send import BroadcastAlreadySent, send_broadcast, start_broadcast
from apps.notifications.models import Notification
from apps.notifications.tests.factories import DeviceFactory, TelegramLinkFactory

pytestmark = pytest.mark.django_db


def _broadcast(**overrides) -> Broadcast:  # type: ignore[no-untyped-def]
    data = {
        "title_ar": "تحديث",
        "body_ar": "نسخة جديدة متاحة",
        "title_en": "Update",
        "body_en": "A new version is available",
    }
    data.update(overrides)
    return Broadcast.objects.create(**data)


def test_send_broadcast_uses_each_users_language(channels, fake_clients) -> None:
    ar_user = UserFactory(language="ar")
    en_user = UserFactory(language="en")
    DeviceFactory(user=ar_user, fcm_token="ar-token")
    DeviceFactory(user=en_user, fcm_token="en-token")
    TelegramLinkFactory(user=en_user, chat_id=55)
    UserFactory(is_staff=True)  # staff are not recipients
    broadcast = _broadcast(status=Broadcast.Status.SENDING)

    count = send_broadcast(broadcast, channels=channels)

    assert count == 2
    sent = dict(fake_clients.push.sent)
    assert sent["ar-token"].title == "تحديث"
    assert sent["en-token"].body == "A new version is available"
    assert fake_clients.bot.sent == [(55, "Update\nA new version is available")]
    broadcast.refresh_from_db()
    assert broadcast.status == Broadcast.Status.SENT
    assert broadcast.recipients_count == 2
    assert broadcast.sent_at is not None
    assert Notification.objects.filter(broadcast=broadcast, kind="broadcast").count() == 2


def test_channel_selection_is_honoured(channels, fake_clients) -> None:
    user = UserFactory()
    DeviceFactory(user=user)
    TelegramLinkFactory(user=user)
    broadcast = _broadcast(send_push=False, status=Broadcast.Status.SENDING)

    send_broadcast(broadcast, channels=channels)

    assert fake_clients.push.sent == []
    assert len(fake_clients.bot.sent) == 1


def test_send_is_idempotent(channels, fake_clients) -> None:
    DeviceFactory(user=UserFactory())
    broadcast = _broadcast(status=Broadcast.Status.SENDING)

    send_broadcast(broadcast, channels=channels)
    Broadcast.objects.filter(pk=broadcast.pk).update(status=Broadcast.Status.SENDING)
    broadcast.refresh_from_db()
    send_broadcast(broadcast, channels=channels)  # re-run after a "crash"

    assert len(fake_clients.push.sent) == 1


def test_start_broadcast_enqueues_once() -> None:
    broadcast = _broadcast()
    enqueued: list = []

    with transaction.atomic():
        start_broadcast(broadcast, enqueue=enqueued.append)
    broadcast.refresh_from_db()
    assert broadcast.status == Broadcast.Status.SENDING

    with pytest.raises(BroadcastAlreadySent):
        start_broadcast(broadcast, enqueue=enqueued.append)


def test_estimated_recipients() -> None:
    with_device = UserFactory()
    DeviceFactory(user=with_device)
    TelegramLinkFactory(user=UserFactory())
    UserFactory()

    assert estimated_recipients(_broadcast()) == 2
    assert estimated_recipients(_broadcast(send_telegram=False)) == 1
    assert estimated_recipients(_broadcast(send_push=False, send_telegram=False)) == 0


def test_send_task(fake_clients) -> None:
    from apps.broadcasts.tasks import send_broadcast as task

    DeviceFactory(user=UserFactory())
    broadcast = _broadcast(status=Broadcast.Status.SENDING)

    assert task(str(broadcast.pk)) == 1
    assert len(fake_clients.push.sent) == 1
