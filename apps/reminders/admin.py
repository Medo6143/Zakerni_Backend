from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from apps.reminders.models import ReminderRule, ScheduledReminder


@admin.register(ReminderRule)
class ReminderRuleAdmin(ModelAdmin):
    list_display = ("user", "item_type", "offsets_minutes", "push_enabled", "telegram_enabled")
    list_filter = ("item_type", "push_enabled", "telegram_enabled")
    search_fields = ("user__moodle_username",)
    raw_id_fields = ("user",)


@admin.register(ScheduledReminder)
class ScheduledReminderAdmin(ModelAdmin):
    """Delivery log: read-only (docs/06, Admin > Logs)."""

    list_display = ("item", "user", "channel", "offset_minutes", "send_at", "status", "attempts")
    list_filter = ("status", "channel")
    search_fields = ("user__moodle_username", "item__title")
    date_hierarchy = "send_at"
    readonly_fields = (
        "user",
        "item",
        "offset_minutes",
        "channel",
        "send_at",
        "status",
        "attempts",
        "sent_at",
        "error",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
