from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.db.models import QuerySet

from apps.core.exceptions import NotFoundAppError
from apps.support.models import Report

if TYPE_CHECKING:
    from apps.accounts.models import User


def reports_for_user(user: User) -> QuerySet[Report]:
    return (
        Report.objects.filter(user=user)
        .prefetch_related("attachments", "replies")
        .order_by("-created_at")
    )


def report_for_user(user: User, report_id: uuid.UUID) -> Report:
    report = reports_for_user(user).filter(id=report_id).first()
    if report is None:
        raise NotFoundAppError()
    return report


def report_for_chat(user: User, report_id: uuid.UUID) -> Report | None:
    """The report if ``user`` may join its live thread (owner or staff), else ``None``."""
    queryset = Report.objects.filter(id=report_id)
    if not user.is_staff:
        queryset = queryset.filter(user=user)
    return queryset.first()


def open_reports_count() -> int:
    return Report.objects.filter(status__in=[Report.Status.NEW, Report.Status.IN_PROGRESS]).count()
