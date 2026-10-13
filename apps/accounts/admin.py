from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.accounts.models import User
from apps.accounts.services.app_auth import set_temporary_password
from apps.broadcasts.forms import DirectNotificationForm
from apps.broadcasts.selectors import channel_availability
from apps.broadcasts.services.direct import create_direct_broadcast
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
    actions = ["set_temporary_password", "send_notification"]
    actions_detail = ["send_notification_detail"]

    def has_send_notification_permission(
        self, request: HttpRequest, object_id: object = None
    ) -> bool:
        user = request.user
        return bool(
            user.is_active
            and user.is_staff
            and user.has_perm("broadcasts.add_broadcast")
            and user.has_perm("accounts.view_user")
        )

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

    @admin.action(description=_("Set a temporary password"))
    def set_temporary_password(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        """Recovery for a student who lost the password (no forgot-password flow yet).
        The generated password is shown once, in the admin message."""
        for user in queryset:
            password = set_temporary_password(user)
            self.message_user(
                request,
                _("Temporary password for %(user)s: %(password)s (shown once)")
                % {"user": user.moodle_username, "password": password},
                messages.SUCCESS,
            )

    @admin.action(description=_("Send notification"), permissions=["send_notification"])
    def send_notification(
        self, request: HttpRequest, queryset: QuerySet[User]
    ) -> HttpResponseRedirect | None:
        users = list(queryset[:2])
        if len(users) != 1:
            self.message_user(
                request, _("Select exactly one user to send a notification."), messages.ERROR
            )
            return None
        return HttpResponseRedirect(
            reverse("admin:accounts_user_send_notification_detail", args=[users[0].pk])
        )

    @action(
        description=_("Send notification"),
        url_path="send-notification",
        permissions=["send_notification"],
    )
    def send_notification_detail(self, request: HttpRequest, object_id: str) -> HttpResponse:
        target = self.get_object(request, object_id)
        if target is None:
            raise Http404
        back_url = reverse("admin:accounts_user_change", args=[target.pk])
        form = DirectNotificationForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            return self._send_direct(request, target, form, back_url)
        context = {
            **self.admin_site.each_context(request),
            "title": _("Send notification"),
            "target": target,
            "form": form,
            "availability": channel_availability(target),
            "back_url": back_url,
        }
        return TemplateResponse(request, "admin/broadcasts/send_notification.html", context)

    def _send_direct(
        self, request: HttpRequest, target: User, form: DirectNotificationForm, back_url: str
    ) -> HttpResponseRedirect:
        from apps.broadcasts.tasks import enqueue_broadcast

        data = form.cleaned_data
        create_direct_broadcast(
            sender=request.user,  # type: ignore[arg-type]
            recipient=target,
            title_ar=data["title_ar"],
            body_ar=data["body_ar"],
            title_en=data["title_en"],
            body_en=data["body_en"],
            send_push=data["send_push"],
            send_telegram=data["send_telegram"],
            enqueue=enqueue_broadcast,
        )
        devices, telegram = channel_availability(target).reachable_through(
            push=data["send_push"], telegram=data["send_telegram"]
        )
        reachable: list[str] = []
        if devices:
            reachable.append(str(_("push (%(n)s device)")) % {"n": devices})
        if telegram:
            reachable.append(str(_("Telegram")))
        if reachable:
            text = _("Notification to %(user)s is being sent through: %(channels)s.") % {
                "user": target.moodle_username,
                "channels": ", ".join(reachable),
            }
            self.message_user(request, text, messages.SUCCESS)
        else:
            text = _(
                "Notification to %(user)s was saved in their history only: "
                "no active device or Telegram link for the selected channels."
            ) % {"user": target.moodle_username}
            self.message_user(request, text, messages.WARNING)
        return HttpResponseRedirect(back_url)

    @admin.display(boolean=True, description=_("Telegram"))
    def telegram_linked(self, obj: User) -> bool:
        return bool(getattr(obj, "has_telegram", False))


admin.site.register(User, UserAdmin)
