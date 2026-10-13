"""Support report use cases ("Report a problem", replies, status changes)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import ValidationAppError
from apps.core.i18n import render_in
from apps.notifications.models import Channel, Notification
from apps.notifications.protocols import Message, NotificationChannel
from apps.notifications.services.history import notify_user
from apps.support.models import Report, ReportAttachment, ReportReply
from apps.support.protocols import ReplyBroadcaster
from apps.support.services.attachments import validate_report_attachments

if TYPE_CHECKING:
    from apps.accounts.models import User

REPLY_TITLE = _("New reply on your report")
_PREVIEW_LENGTH = 200
_MAX_BODY_LENGTH = 5000


def create_report(
    user: User,
    *,
    category: str,
    description: str,
    device_info: dict[str, Any] | None = None,
    app_version: str = "",
    attachments: Sequence[UploadedFile] = (),
) -> Report:
    if category not in Report.Category.values:
        raise ValidationAppError(details={"category": [str(_("Unknown category."))]})
    validate_report_attachments(attachments)
    with transaction.atomic():
        report = Report.objects.create(
            user=user,
            category=category,
            description=description,
            device_info=device_info or {},
            app_version=app_version[:32],
        )
        for upload in attachments:
            ReportAttachment.objects.create(report=report, file=upload)
    return report


def _broadcast_on_commit(reply: ReportReply, broadcaster: ReplyBroadcaster) -> None:
    # Live clients only ever see replies that are really stored.
    transaction.on_commit(lambda: broadcaster.reply_created(reply))


def add_user_reply(
    report: Report, user: User, body: str, *, broadcaster: ReplyBroadcaster
) -> ReportReply:
    """Student follow-up in their own report thread. The status is left unchanged.
    Broadcast live to the thread after commit."""
    reply = ReportReply.objects.create(report=report, author=user, is_staff=False, body=body)
    _broadcast_on_commit(reply, broadcaster)
    return reply


def add_staff_reply(
    report: Report,
    author: User,
    body: str,
    *,
    channels: Mapping[str, NotificationChannel],
    broadcaster: ReplyBroadcaster,
) -> ReportReply:
    """Admin reply: stored in the thread, broadcast live after commit, and pushed to
    the student (history row too), so a student without the screen open still hears."""
    reply = ReportReply.objects.create(report=report, author=author, is_staff=True, body=body)
    _broadcast_on_commit(reply, broadcaster)
    student = report.user
    if student is not None and student.is_active:
        preview = body if len(body) <= _PREVIEW_LENGTH else body[: _PREVIEW_LENGTH - 3] + "..."
        message = Message(
            title=render_in(student.language, REPLY_TITLE),
            body=preview,
            data={
                "kind": "report_reply",
                "report_id": str(report.pk),
                "route": f"/reports/{report.pk}",
            },
        )
        notify_user(
            student,
            message,
            kind=Notification.Kind.REPORT_REPLY,
            channels=channels,
            codes={Channel.PUSH.value},
            report=report,
        )
    return reply


def add_chat_message(
    report: Report,
    author: User,
    body: str,
    *,
    channels: Mapping[str, NotificationChannel],
    broadcaster: ReplyBroadcaster,
) -> ReportReply:
    """A message typed in the live thread: staff members post a staff reply (with the
    push to the student), the report owner posts a follow-up."""
    body = (body or "").strip() if isinstance(body, str) else ""
    if not body:
        raise ValidationAppError(details={"body": [str(_("This field may not be blank."))]})
    if len(body) > _MAX_BODY_LENGTH:
        raise ValidationAppError(
            details={"body": [str(_("Ensure this field has no more than 5000 characters."))]}
        )
    if author.is_staff:
        return add_staff_reply(report, author, body, channels=channels, broadcaster=broadcaster)
    return add_user_reply(report, author, body, broadcaster=broadcaster)


def change_report_status(report: Report, status: str) -> Report:
    if status not in Report.Status.values:
        raise ValidationAppError(details={"status": [str(_("Unknown status."))]})
    if report.status != status:
        report.status = status
        report.save(update_fields=["status", "updated_at"])
    return report
