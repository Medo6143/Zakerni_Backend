import factory
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.notifications.models import Device, Notification, TelegramLink


class DeviceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Device

    user = factory.SubFactory(UserFactory)
    fcm_token = factory.Sequence(lambda n: f"fcm-token-{n}")
    platform = Device.Platform.ANDROID
    is_active = True
    last_seen_at = factory.LazyFunction(timezone.now)


class TelegramLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TelegramLink

    user = factory.SubFactory(UserFactory)
    chat_id = factory.Sequence(lambda n: 7000 + n)
    username = factory.Sequence(lambda n: f"tg_user{n}")
    linked_at = factory.LazyFunction(timezone.now)


class NotificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Notification

    user = factory.SubFactory(UserFactory)
    kind = Notification.Kind.SYSTEM
    title = factory.Sequence(lambda n: f"Notification {n}")
    body = "Body"
