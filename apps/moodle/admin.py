from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from apps.moodle.models import MoodleAccount, SyncLog


class MoodleAccountAdmin(ModelAdmin):
    """The encrypted token is intentionally excluded from every field list."""

    list_display = ("user", "site_url", "status", "last_synced_at")
    list_filter = ("status",)
    search_fields = ("user__moodle_username",)
    readonly_fields = ("user", "moodle_user_id", "last_synced_at", "last_sync_error")
    fields = ("user", "site_url", "moodle_user_id", "status", "last_synced_at", "last_sync_error")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


class SyncLogAdmin(ModelAdmin):
    """Read-only log (docs/06, Admin > Logs)."""

    list_display = (
        "moodle_account",
        "status",
        "started_at",
        "finished_at",
        "items_created",
        "items_updated",
        "items_removed",
    )
    list_filter = ("status",)
    search_fields = ("moodle_account__user__moodle_username",)
    readonly_fields = (
        "moodle_account",
        "status",
        "started_at",
        "finished_at",
        "items_created",
        "items_updated",
        "items_removed",
        "error",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


admin.site.register(MoodleAccount, MoodleAccountAdmin)
admin.site.register(SyncLog, SyncLogAdmin)
