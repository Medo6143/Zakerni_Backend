from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from apps.sis.models import SisAccount, SisSyncLog


class SisAccountAdmin(ModelAdmin):
    """The encrypted password is intentionally excluded from every field list."""

    list_display = ("user", "username", "status", "last_synced_at")
    list_filter = ("status",)
    search_fields = ("user__moodle_username", "username")
    readonly_fields = ("user", "username", "last_synced_at", "last_sync_error")
    fields = ("user", "username", "status", "last_synced_at", "last_sync_error")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


class SisSyncLogAdmin(ModelAdmin):
    """Read-only log."""

    list_display = (
        "sis_account",
        "status",
        "started_at",
        "finished_at",
        "items_created",
        "items_updated",
        "items_removed",
    )
    list_filter = ("status",)
    search_fields = ("sis_account__user__moodle_username",)
    readonly_fields = (
        "sis_account",
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


admin.site.register(SisAccount, SisAccountAdmin)
admin.site.register(SisSyncLog, SisSyncLogAdmin)
