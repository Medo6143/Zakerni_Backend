from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet

from apps.moodle.models import CourseAnnouncement, MoodleAccount, SyncLog


def moodle_account_for_user(user_id: Any) -> MoodleAccount | None:
    return MoodleAccount.objects.filter(user_id=user_id).first()


def moodle_account_by_id(account_id: Any) -> MoodleAccount | None:
    return MoodleAccount.objects.select_related("user").filter(id=account_id).first()


def active_moodle_account_ids() -> list[uuid.UUID]:
    return list(
        MoodleAccount.objects.filter(status=MoodleAccount.Status.ACTIVE, user__is_active=True)
        .exclude(token_encrypted="")  # device mode: nothing the server can fetch
        .values_list("id", flat=True)
    )


def recent_failed_syncs(limit: int = 10) -> QuerySet[SyncLog]:
    return (
        SyncLog.objects.filter(status=SyncLog.Status.FAILED)
        .select_related("moodle_account__user")
        .order_by("-started_at")[:limit]
    )


def announcements_for_user(user: Any, course_id: Any = None) -> QuerySet[CourseAnnouncement]:
    queryset = CourseAnnouncement.objects.filter(user=user).select_related("course")
    if course_id is not None:
        queryset = queryset.filter(course_id=course_id)
    return queryset
