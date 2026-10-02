"""Calendar data: courses, enrollments, items and recurring lecture schedules.

See ``docs/04-erd.md`` for the authoritative field list and constraints.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, UUIDModel


class ItemType(models.TextChoices):
    """Single enum of item types. Adding a type = new value here + a default rule
    in ``apps.reminders.defaults`` + a phrase in ``apps.reminders.services.messages``."""

    QUIZ = "quiz", _("Quiz")
    TMA = "tma", _("TMA")
    EXAM = "exam", _("Exam")
    LECTURE = "lecture", _("Lecture")


class ItemSource(models.TextChoices):
    MOODLE = "moodle", _("Moodle")
    MANUAL = "manual", _("Manual")
    SIS = "sis", _("SIS")


class ItemStatus(models.TextChoices):
    """The student's personal status on an item (independent of reminders).

    Empty string means unset (same as ``planned``). Adding a status = new value
    here + a meta entry in the mobile ``itemStatusMeta`` registry. No ``if`` chains."""

    PLANNED = "planned", _("Planned")
    ATTENDED = "attended", _("Attended")
    POSTPONED = "postponed", _("Postponed")
    CANCELLED = "cancelled", _("Cancelled")
    DONE = "done", _("Done")


MANUAL_ITEM_TYPES = (ItemType.QUIZ, ItemType.EXAM, ItemType.LECTURE)
# Types a student creates directly through ``/items`` (lectures go through ``/lectures``).
MANUAL_CREATE_TYPES = (ItemType.QUIZ, ItemType.EXAM)


class Course(UUIDModel, TimeStampedModel):
    moodle_course_id = models.PositiveIntegerField(_("Moodle course id"), unique=True)
    code = models.CharField(_("code"), max_length=64, blank=True)
    name = models.CharField(_("name"), max_length=255, blank=True)

    class Meta:
        db_table = "schedule_course"
        ordering = ("code",)
        verbose_name = _("course")
        verbose_name_plural = _("courses")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}" if self.code else self.name


class Enrollment(UUIDModel, TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    is_muted = models.BooleanField(_("muted"), default=False)
    is_active = models.BooleanField(_("active"), default=True)
    # Filled by the Moodle sync (student's group(s) and its non-student members).
    group_name = models.CharField(_("group"), max_length=255, blank=True)
    tutor_name = models.CharField(_("tutor"), max_length=255, blank=True)

    class Meta:
        db_table = "schedule_enrollment"
        verbose_name = _("enrollment")
        verbose_name_plural = _("enrollments")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course"], name="enrollment_unique_user_course"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.course_id}"


class LectureSchedule(UUIDModel, TimeStampedModel):
    """A weekly recurring lecture. ``weekdays`` uses 0=Mon..6=Sun (Python ``weekday()``).

    ``start_time`` is local time in ``timezone``; generated items are stored in UTC.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lecture_schedules"
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lecture_schedules",
    )
    title = models.CharField(_("title"), max_length=255)
    weekdays = models.JSONField(_("weekdays"), default=list)
    start_time = models.TimeField(_("start time"))
    duration_minutes = models.PositiveSmallIntegerField(_("duration (minutes)"))
    location = models.CharField(_("location"), max_length=255, blank=True)
    starts_on = models.DateField(_("starts on"))
    ends_on = models.DateField(_("ends on"))
    timezone = models.CharField(_("timezone"), max_length=64, default="Africa/Cairo")
    # ``manual`` (student-entered) or ``sis`` (imported timetable, read-only in the app).
    # Generated occurrences inherit the source.
    source = models.CharField(
        _("source"), max_length=16, choices=ItemSource.choices, default=ItemSource.MANUAL
    )
    # NULL for manual schedules; the SIS sync's stable key otherwise.
    external_id = models.CharField(  # noqa: DJ001
        _("external id"), max_length=64, null=True, blank=True
    )

    class Meta:
        db_table = "schedule_lecture_schedule"
        ordering = ("starts_on", "start_time")
        verbose_name = _("lecture schedule")
        verbose_name_plural = _("lecture schedules")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "source", "external_id"],
                condition=Q(external_id__isnull=False),
                name="lecture_schedule_unique_external",
            ),
            models.CheckConstraint(
                condition=Q(ends_on__gte=models.F("starts_on")),
                name="lecture_schedule_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(duration_minutes__gt=0),
                name="lecture_schedule_positive_duration",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class Item(UUIDModel, TimeStampedModel):
    """A calendar entry (quiz, TMA, exam or lecture occurrence), always owned by one user.

    ``scheduled_at`` is the reminder anchor: quiz = close time, TMA = due date,
    exam/lecture = start. It is nullable because Moodle items without a
    close/due date are stored but never scheduled.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="items"
    )
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="items"
    )
    lecture_schedule = models.ForeignKey(
        LectureSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )
    type = models.CharField(_("type"), max_length=16, choices=ItemType.choices)
    source = models.CharField(_("source"), max_length=16, choices=ItemSource.choices)
    # NULL (not "") for manual items: the partial unique index is WHERE external_id IS NOT NULL.
    external_id = models.CharField(  # noqa: DJ001
        _("external id"), max_length=64, null=True, blank=True
    )
    title = models.CharField(_("title"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    # The student's own status/note on the item (any type/source). Independent of reminders.
    status = models.CharField(
        _("status"), max_length=16, choices=ItemStatus.choices, blank=True, default=""
    )
    note = models.TextField(_("note"), blank=True, default="")
    location = models.CharField(_("location"), max_length=255, blank=True)
    url = models.URLField(_("url"), max_length=500, blank=True)
    available_from = models.DateTimeField(_("available from"), null=True, blank=True)
    scheduled_at = models.DateTimeField(_("scheduled at"), null=True, blank=True)
    ends_at = models.DateTimeField(_("ends at"), null=True, blank=True)
    is_muted = models.BooleanField(_("muted"), default=False)
    deleted_at = models.DateTimeField(_("deleted at"), null=True, blank=True)

    class Meta:
        db_table = "schedule_item"
        ordering = ("scheduled_at",)
        verbose_name = _("item")
        verbose_name_plural = _("items")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "source", "type", "external_id"],
                condition=Q(external_id__isnull=False),
                name="item_unique_external",
            ),
            models.UniqueConstraint(
                fields=["lecture_schedule", "scheduled_at"],
                name="item_unique_lecture_occurrence",
            ),
            models.CheckConstraint(
                condition=Q(type__in=[c.value for c in ItemType]),
                name="item_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(source__in=[c.value for c in ItemSource]),
                name="item_source_valid",
            ),
            models.CheckConstraint(
                condition=~Q(source=ItemSource.MANUAL.value)
                | Q(type__in=[t.value for t in MANUAL_ITEM_TYPES]),
                name="item_manual_type_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "scheduled_at"],
                condition=Q(deleted_at__isnull=True),
                name="item_user_sched_live_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_editable(self) -> bool:
        """Only manual exams and quizzes are edited through ``/items``; lecture occurrences are
        managed through their ``LectureSchedule``; Moodle items are read-only."""
        return self.source == ItemSource.MANUAL and self.lecture_schedule_id is None
