from django.urls import path

from apps.notifications.api.views import (
    DeviceDetailView,
    DeviceRegisterView,
    MarkReadView,
    NotificationListView,
    TelegramLinkView,
    TelegramStatusView,
    TelegramWebhookView,
    UnreadCountView,
)

urlpatterns = [
    path("devices", DeviceRegisterView.as_view(), name="devices"),
    path("devices/<str:fcm_token>", DeviceDetailView.as_view(), name="device-detail"),
    path("telegram", TelegramStatusView.as_view(), name="telegram"),
    path("telegram/link", TelegramLinkView.as_view(), name="telegram-link"),
    path("telegram/webhook", TelegramWebhookView.as_view(), name="telegram-webhook"),
    path("notifications", NotificationListView.as_view(), name="notifications"),
    path(
        "notifications/unread-count", UnreadCountView.as_view(), name="notifications-unread-count"
    ),
    path("notifications/mark-read", MarkReadView.as_view(), name="notifications-mark-read"),
]
