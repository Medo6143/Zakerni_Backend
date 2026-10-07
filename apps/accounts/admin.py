from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.accounts.models import User
from apps.accounts.services.device_auth import reset_device_binding
from apps.moodle.models import MoodleAccount
from apps.notifications.models import TelegramLink


class UserAdmin(DjangoUserAdmin, ModelAdmin):
    """The Moodle LMS token is never exposed here (see apps.moodle.admin)."""

    model = User
    ordering = ("-date_joined",)
    list_display = (
        "moodle_username",
        "full_name",
        "language",
        "lms_status",
        "active_devices",
        "telegram_linked",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_staff", "is_active", "language", "moodle_account__status")
    search_fields = ("moodle_username", "full_name", "email")
    fieldsets = (
        (None, {"fields": ("moodle_username", "password")}),
        (_("Profile"), {"fields": ("full_name", "email", "language", "timezone")}),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (
            _("Important dates"),
            {"fields": ("last_login", "date_joined", "reminder_defaults_confirmed_at")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("moodle_username", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("date_joined", "reminder_defaults_confirmed_at")
    actions = ["reset_device_binding"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[User]:
        return (
            super()
            .get_queryset(request)
            .select_related("moodle_account")
            .annotate(
                active_devices_count=Count("devices", filter=Q(devices__is_active=True)),
                has_telegram=Exists(TelegramLink.objects.filter(user=OuterRef("pk"))),
            )
        )

    @admin.display(description=_("LMS status"))
    def lms_status(self, obj: User) -> str:
        try:
            account: MoodleAccount = obj.moodle_account  # type: ignore[attr-defined]
        except MoodleAccount.DoesNotExist:
            return "-"
        return str(account.get_status_display())

    @admin.display(description=_("active devices"))
    def active_devices(self, obj: User) -> int:
        return int(getattr(obj, "active_devices_count", 0))

    @admin.action(description=_("Reset device binding"))
    def reset_device_binding(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        """Lets a student who reinstalled the app claim the account from a new device."""
        count = 0
        for user in queryset:
            reset_device_binding(user)
            count += 1
        self.message_user(
            request,
            _("Device binding reset for %(count)d user(s).") % {"count": count},
            messages.SUCCESS,
        )

    @admin.display(boolean=True, description=_("Telegram"))
    def telegram_linked(self, obj: User) -> bool:
        return bool(getattr(obj, "has_telegram", False))


admin.site.register(User, UserAdmin)
