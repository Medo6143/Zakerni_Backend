from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from apps.notifications.models import Device, Notification, TelegramLink


@admin.register(Device)
class DeviceAdmin(ModelAdmin):
    """The FCM token itself is not displayed."""

    list_display = ("user", "platform", "model", "app_version", "is_active", "last_seen_at")
    list_filter = ("platform", "is_active")
    search_fields = ("user__moodle_username", "model")
    fields = ("user", "platform", "model", "os_version", "app_version", "is_active", "last_seen_at")
    readonly_fields = ("user", "platform", "model", "os_version", "app_version", "last_seen_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(TelegramLink)
class TelegramLinkAdmin(ModelAdmin):
    list_display = ("user", "username", "linked_at")
    search_fields = ("user__moodle_username", "username")
    readonly_fields = ("user", "chat_id", "username", "linked_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ("title", "user", "kind", "created_at", "read_at")
    list_filter = ("kind",)
    search_fields = ("user__moodle_username", "title")
    readonly_fields = (
        "user",
        "kind",
        "title",
        "body",
        "item",
        "report",
        "broadcast",
        "read_at",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
