"""Read-only calendar queries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.db.models import Count, Min, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

from apps.core.exceptions import NotFoundAppError
from apps.reminders.models import ScheduledReminder
from apps.schedule.models import Enrollment, Item, LectureSchedule

if TYPE_CHECKING:
    from apps.accounts.models import User


def _live_items(user: User) -> QuerySet[Item]:
    """Not deleted, and either without a course or in a course the user is still
    actively enrolled in (items of past-term enrollments are hidden)."""
    active_courses = Enrollment.objects.filter(user=user, is_active=True).values("course_id")
    return Item.objects.filter(user=user, deleted_at__isnull=True).filter(
        Q(course__isnull=True) | Q(course_id__in=active_courses)
    )


def _with_reminder_info(queryset: QuerySet[Item]) -> QuerySet[Item]:
    return queryset.select_related("course", "reminder_override").annotate(
        next_reminder_at=Min(
            "scheduled_reminders__send_at",
            filter=Q(scheduled_reminders__status=ScheduledReminder.Status.PENDING),
        )
    )


def items_in_range(
    user: User,
    start: datetime,
    end: datetime,
    *,
    item_type: str | None = None,
    course_id: uuid.UUID | None = None,
) -> QuerySet[Item]:
    queryset = _live_items(user).filter(scheduled_at__gte=start, scheduled_at__lt=end)
    if item_type:
        queryset = queryset.filter(type=item_type)
    if course_id:
        queryset = queryset.filter(course_id=course_id)
    return _with_reminder_info(queryset).order_by("scheduled_at", "title")


def item_for_user(user: User, item_id: uuid.UUID) -> Item:
    item = _with_reminder_info(_live_items(user).filter(id=item_id)).first()
    if item is None:
        raise NotFoundAppError()
    return item


def lecture_schedules_for_user(user: User) -> QuerySet[LectureSchedule]:
    return LectureSchedule.objects.filter(user=user).select_related("course")


def lecture_schedule_for_user(user: User, schedule_id: uuid.UUID) -> LectureSchedule:
    schedule = lecture_schedules_for_user(user).filter(id=schedule_id).first()
    if schedule is None:
        raise NotFoundAppError()
    return schedule


def active_lecture_schedules(today_date: object) -> QuerySet[LectureSchedule]:
    return LectureSchedule.objects.filter(ends_on__gte=today_date).select_related("user")


def enrollments_for_user(user: User) -> QuerySet[Enrollment]:
    """Active enrollments with ``upcoming_count`` (live items from now on)."""
    now = timezone.now()
    upcoming = (
        Item.objects.filter(
            user=user,
            course_id=OuterRef("course_id"),
            deleted_at__isnull=True,
            scheduled_at__gte=now,
        )
        .order_by()
        .values("course_id")
        .annotate(total=Count("id"))
        .values("total")
    )
    return (
        Enrollment.objects.filter(user=user, is_active=True)
        .select_related("course")
        .annotate(upcoming_count=Subquery(upcoming))
        .order_by("course__code")
    )


def enrollment_for_user(user: User, course_id: uuid.UUID) -> Enrollment:
    enrollment = enrollments_for_user(user).filter(course_id=course_id).first()
    if enrollment is None:
        raise NotFoundAppError()
    return enrollment


def is_enrolled(user: User, course_id: uuid.UUID) -> bool:
    return Enrollment.objects.filter(user=user, course_id=course_id, is_active=True).exists()


COURSE_DETAIL_DAYS = 30


@dataclass(frozen=True)
class CourseDetail:
    enrollment: Enrollment
    upcoming_items: QuerySet[Item]
    lecture_schedules: QuerySet[LectureSchedule]


def course_detail_for_user(user: User, course_id: uuid.UUID) -> CourseDetail:
    """An active enrollment of ``user`` with its next 30 days of items (all types) and the
    user's lecture schedules for the course. Raises ``NotFoundAppError`` otherwise."""
    enrollment = enrollment_for_user(user, course_id)
    now = timezone.now()
    return CourseDetail(
        enrollment=enrollment,
        upcoming_items=items_in_range(
            user, now, now + timedelta(days=COURSE_DETAIL_DAYS), course_id=course_id
        ),
        lecture_schedules=lecture_schedules_for_user(user).filter(course_id=course_id),
    )


def tutor_name_for(user: User, course_id: uuid.UUID | None) -> str:
    """The tutor name from the user's enrollment in ``course_id``, or ""."""
    if course_id is None:
        return ""
    name = (
        Enrollment.objects.filter(user=user, course_id=course_id)
        .values_list("tutor_name", flat=True)
        .first()
    )
    return name or ""
