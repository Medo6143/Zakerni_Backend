"""Broadcasts admin: AR + EN title/body, channels, recipients preview, "Send now"."""

from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.broadcasts.models import Broadcast
from apps.broadcasts.selectors import broadcast_by_id, estimated_recipients
from apps.broadcasts.services.send import BroadcastAlreadySent, start_broadcast


def _enqueue(broadcast_id: Any) -> None:
    from apps.broadcasts.tasks import send_broadcast

    send_broadcast.delay(str(broadcast_id))


@admin.register(Broadcast)
class BroadcastAdmin(ModelAdmin):
    list_display = (
        "__str__",
        "status",
        "send_push",
        "send_telegram",
        "recipients_count",
        "sent_at",
    )
    list_filter = ("status",)
    search_fields = ("title_ar", "title_en")
    fieldsets = (
        (_("Arabic"), {"fields": ("title_ar", "body_ar")}),
        (_("English"), {"fields": ("title_en", "body_en")}),
        (_("Channels"), {"fields": ("send_push", "send_telegram")}),
        (
            _("Delivery"),
            {
                "fields": (
                    "estimated_recipients",
                    "status",
                    "recipients_count",
                    "sent_at",
                    "created_by",
                )
            },
        ),
    )
    readonly_fields = (
        "estimated_recipients",
        "status",
        "recipients_count",
        "sent_at",
        "created_by",
    )
    actions = ("send_now",)
    actions_detail = ("send_now_detail",)

    def get_readonly_fields(self, request: HttpRequest, obj: Broadcast | None = None) -> Any:
        if obj is not None and obj.status != Broadcast.Status.DRAFT:
            return (
                "title_ar",
                "body_ar",
                "title_en",
                "body_en",
                "send_push",
                "send_telegram",
                *self.readonly_fields,
            )
        return self.readonly_fields

    @admin.display(description=_("estimated recipients"))
    def estimated_recipients(self, obj: Broadcast | None) -> int | str:
        if obj is None or obj.pk is None:
            return "-"
        return estimated_recipients(obj)

    def save_model(self, request: HttpRequest, obj: Broadcast, form: Any, change: bool) -> None:
        if not change:
            obj.created_by = request.user  # type: ignore[assignment]
        super().save_model(request, obj, form, change)

    def _start(self, request: HttpRequest, broadcast: Broadcast) -> bool:
        try:
            start_broadcast(broadcast, enqueue=_enqueue)
        except BroadcastAlreadySent as exc:
            self.message_user(request, str(exc.message), messages.WARNING)
            return False
        return True

    @admin.action(description=_("Send now"))
    def send_now(self, request: HttpRequest, queryset: QuerySet[Broadcast]) -> None:
        started = sum(1 for broadcast in queryset if self._start(request, broadcast))
        if started:
            self.message_user(request, _("Broadcast is being sent."), messages.SUCCESS)

    @action(description=_("Send now"), url_path="send-now")
    def send_now_detail(self, request: HttpRequest, object_id: str) -> HttpResponseRedirect:
        broadcast = broadcast_by_id(object_id)
        if broadcast is not None and self._start(request, broadcast):
            self.message_user(request, _("Broadcast is being sent."), messages.SUCCESS)
        return HttpResponseRedirect(reverse("admin:broadcasts_broadcast_change", args=[object_id]))
