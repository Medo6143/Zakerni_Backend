"""Reports admin: queue filtered by status/category, detail with attachments and
device info, inline staff reply (pushes to the student) and status changes."""

from __future__ import annotations

import json
from typing import Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from apps.support.models import Report, ReportAttachment, ReportReply
from apps.support.services import reports as report_services
from config import container


class ReportAttachmentInline(TabularInline):
    model = ReportAttachment
    extra = 0
    fields = ("preview", "created_at")
    readonly_fields = ("preview", "created_at")
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    @admin.display(description=_("image"))
    def preview(self, obj: ReportAttachment) -> str:
        if not obj.file:
            return "-"
        return format_html(
            '<a href="{0}" target="_blank" rel="noopener"><img src="{0}" style="max-height:160px"></a>',
            obj.file.url,
        )


class ReportReplyAddInline(TabularInline):
    """Empty row for a new staff reply; saving it pushes to the student."""

    model = ReportReply
    extra = 1
    max_num = 1
    fields = ("body",)
    can_delete = False
    verbose_name = _("new reply")
    verbose_name_plural = _("reply to the student")

    def get_queryset(self, request: HttpRequest) -> QuerySet[ReportReply]:
        return super().get_queryset(request).none()


@admin.register(Report)
class ReportAdmin(ModelAdmin):
    list_display = ("category", "status", "user", "app_version", "created_at")
    list_filter = ("status", "category")
    search_fields = ("description", "user__moodle_username")
    date_hierarchy = "created_at"
    fields = (
        "user",
        "category",
        "status",
        "description",
        "app_version",
        "device_info_pretty",
        "created_at",
    )
    readonly_fields = (
        "user",
        "category",
        "description",
        "app_version",
        "device_info_pretty",
        "created_at",
    )
    # The conversation is shown (and answered) live over the report WebSocket; the
    # "new reply" inline stays as a fallback that works without JavaScript.
    inlines = (ReportAttachmentInline, ReportReplyAddInline)
    change_form_after_template = "admin/support/report_live_thread.html"
    actions = ("mark_in_progress", "mark_resolved", "mark_closed")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> Any:
        extra_context = {
            **(extra_context or {}),
            "live_thread_i18n": {
                "staff": str(_("Staff")),
                "student": str(_("Student")),
                "connected": str(_("Live")),
                "disconnected": str(_("Offline, reconnecting")),
            },
        }
        return super().change_view(request, object_id, form_url, extra_context)

    @admin.display(description=_("device info"))
    def device_info_pretty(self, obj: Report) -> str:
        if not obj.device_info:
            return "-"
        return format_html_join(
            "",
            "<div><strong>{}</strong>: {}</div>",
            (
                (key, json.dumps(value, ensure_ascii=False))
                for key, value in obj.device_info.items()
            ),
        )

    def save_model(self, request: HttpRequest, obj: Report, form: Any, change: bool) -> None:
        # Only ``status`` is editable; route the change through the service.
        if change and "status" in form.changed_data:
            new_status = obj.status
            obj.status = form.initial.get("status", obj.status)
            report_services.change_report_status(obj, new_status)
        elif not change:
            super().save_model(request, obj, form, change)

    def save_formset(self, request: HttpRequest, form: Any, formset: Any, change: bool) -> None:
        if formset.model is ReportReply and isinstance(formset.instance, Report):
            # Replies never go through formset.save(): a new staff reply is created by
            # the service, which also pushes it to the student. Existing ones are read-only.
            formset.new_objects, formset.changed_objects, formset.deleted_objects = [], [], []
            channels = None
            for inline_form in formset.forms:
                body = (
                    (inline_form.cleaned_data or {}).get("body")
                    if inline_form.has_changed()
                    else None
                )
                if not body:
                    continue
                channels = channels or container.notification_channels()
                reply = report_services.add_staff_reply(
                    formset.instance,
                    request.user,
                    body,
                    channels=channels,
                    broadcaster=container.reply_broadcaster(),
                )
                formset.new_objects.append(reply)
                self.message_user(request, _("Reply sent to the student."), messages.SUCCESS)
            return
        super().save_formset(request, form, formset, change)

    def _set_status(self, request: HttpRequest, queryset: QuerySet[Report], status: str) -> None:
        for report in queryset:
            report_services.change_report_status(report, status)
        self.message_user(request, _("Status updated."), messages.SUCCESS)

    @admin.action(description=_("Mark as in progress"))
    def mark_in_progress(self, request: HttpRequest, queryset: QuerySet[Report]) -> None:
        self._set_status(request, queryset, Report.Status.IN_PROGRESS)

    @admin.action(description=_("Mark as resolved"))
    def mark_resolved(self, request: HttpRequest, queryset: QuerySet[Report]) -> None:
        self._set_status(request, queryset, Report.Status.RESOLVED)

    @admin.action(description=_("Mark as closed"))
    def mark_closed(self, request: HttpRequest, queryset: QuerySet[Report]) -> None:
        self._set_status(request, queryset, Report.Status.CLOSED)
