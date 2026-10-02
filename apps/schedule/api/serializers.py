from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.schedule.models import (
    MANUAL_CREATE_TYPES,
    Course,
    Enrollment,
    Item,
    ItemStatus,
    ItemType,
    LectureSchedule,
)

MAX_RANGE_DAYS = 62


class CourseSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ("id", "code", "name")


class ItemRemindersSerializer(serializers.Serializer):
    offsets_minutes = serializers.ListField(child=serializers.IntegerField())
    is_override = serializers.BooleanField()
    next_at = serializers.DateTimeField(allow_null=True)


class ItemSerializer(serializers.ModelSerializer):
    """A calendar item. ``reminders`` shows the effective offsets (per-item override or the
    type rule) and the next pending reminder time."""

    # Serializer context: ``rules`` = {item_type: ReminderRule} for the requesting user.

    course = CourseSummarySerializer(allow_null=True, read_only=True)
    is_editable = serializers.BooleanField(read_only=True)
    reminders = serializers.SerializerMethodField()
    lecture_schedule_id = serializers.UUIDField(allow_null=True, read_only=True)

    class Meta:
        model = Item
        fields = (
            "id",
            "type",
            "source",
            "title",
            "course",
            "available_from",
            "scheduled_at",
            "ends_at",
            "location",
            "url",
            "status",
            "note",
            "is_muted",
            "is_editable",
            "reminders",
            "lecture_schedule_id",
        )
        read_only_fields = fields

    @extend_schema_field(ItemRemindersSerializer)
    def get_reminders(self, obj: Item) -> dict:
        override = getattr(obj, "reminder_override", None)
        if override is not None:
            offsets = list(override.offsets_minutes)
        else:
            rule = self.context.get("rules", {}).get(obj.type)
            offsets = list(rule.offsets_minutes) if rule is not None else []
        return {
            "offsets_minutes": offsets,
            "is_override": override is not None,
            "next_at": getattr(obj, "next_reminder_at", None),
        }


@extend_schema_field({"type": "string", "description": "ISO 8601 datetime, or `now`"})
class DateTimeOrNowField(serializers.DateTimeField):
    """A datetime that also accepts the literal ``now`` (the current server time)."""

    def to_internal_value(self, value):  # type: ignore[no-untyped-def]
        if isinstance(value, str) and value.strip().lower() == "now":
            return timezone.now()
        return super().to_internal_value(value)


class ItemRangeQuerySerializer(serializers.Serializer):
    # ``from`` is a Python keyword, so it is added to the class namespace directly.
    locals()["from"] = DateTimeOrNowField(
        help_text="Range start (inclusive): ISO 8601, or `now` for upcoming items"
    )
    to = serializers.DateTimeField(
        required=False,
        help_text="Range end (exclusive), at most 62 days after `from`. Default: `from` + 62 days",
    )
    type = serializers.ChoiceField(
        choices=ItemType.choices, required=False, help_text="Only items of this type"
    )
    course = serializers.UUIDField(required=False, help_text="Only items of this course")

    def validate(self, attrs: dict) -> dict:
        if "to" not in attrs:
            attrs["to"] = attrs["from"] + timedelta(days=MAX_RANGE_DAYS)
        if attrs["to"] <= attrs["from"]:
            raise serializers.ValidationError({"to": [_("`to` must be after `from`.")]})
        if attrs["to"] - attrs["from"] > timedelta(days=MAX_RANGE_DAYS):
            raise serializers.ValidationError({"to": [_("The range can be at most 62 days.")]})
        return attrs


class ItemHistoryQuerySerializer(serializers.Serializer):
    status = serializers.CharField(
        required=False,
        help_text="Comma separated statuses (e.g. `attended,done`). Default: any set status",
    )
    type = serializers.ChoiceField(
        choices=ItemType.choices, required=False, help_text="Only items of this type"
    )
    course = serializers.UUIDField(required=False, help_text="Only items of this course")
    cursor = serializers.CharField(required=False, help_text="Pagination cursor")

    def validate_status(self, value: str) -> list[str]:
        statuses = [part.strip() for part in value.split(",") if part.strip()]
        invalid = [part for part in statuses if part not in ItemStatus.values]
        if invalid:
            raise serializers.ValidationError(_("Unknown status."))
        return statuses


class ItemCreateSerializer(serializers.Serializer):
    """``ItemCreate``: exams and quizzes (lectures are created through ``/lectures``)."""

    type = serializers.ChoiceField(
        choices=[t.value for t in MANUAL_CREATE_TYPES], default=ItemType.EXAM.value
    )
    available_from = serializers.DateTimeField(required=False, allow_null=True)
    course_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=255)
    scheduled_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ItemUpdateSerializer(serializers.Serializer):
    available_from = serializers.DateTimeField(required=False, allow_null=True)
    course_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=255, required=False)
    scheduled_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ItemMuteSerializer(serializers.Serializer):
    is_muted = serializers.BooleanField()


class ItemStatusNoteSerializer(serializers.Serializer):
    """The student's personal status and/or note on an item (both optional)."""

    status = serializers.ChoiceField(
        choices=[*ItemStatus.choices, ("", "")],
        required=False,
        help_text="One of the item statuses, or empty string to clear it",
    )
    note = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, trim_whitespace=False
    )


class LectureScheduleSerializer(serializers.ModelSerializer):
    course = CourseSummarySerializer(allow_null=True, read_only=True)
    start_time = serializers.TimeField(format="%H:%M")
    weekdays = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6))

    class Meta:
        model = LectureSchedule
        fields = (
            "id",
            "course",
            "title",
            "weekdays",
            "start_time",
            "duration_minutes",
            "location",
            "starts_on",
            "ends_on",
            "timezone",
        )
        read_only_fields = fields


class LectureScheduleWriteSerializer(serializers.Serializer):
    course_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=255)
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        min_length=1,
        max_length=7,
        help_text="0=Monday .. 6=Sunday",
    )
    start_time = serializers.TimeField(
        input_formats=["%H:%M", "%H:%M:%S"], help_text="Local time, e.g. 18:00"
    )
    duration_minutes = serializers.IntegerField(min_value=1, max_value=600)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()


class CourseSerializer(serializers.ModelSerializer):
    """An enrolled course. ``id`` is the course id; ``upcoming_count`` counts items from now on."""

    id = serializers.UUIDField(source="course.id", read_only=True)
    code = serializers.CharField(source="course.code", read_only=True)
    name = serializers.CharField(source="course.name", read_only=True)
    upcoming_count = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = ("id", "code", "name", "is_muted", "upcoming_count")
        read_only_fields = fields

    def get_upcoming_count(self, obj: Enrollment) -> int:
        return int(getattr(obj, "upcoming_count", None) or 0)


class CourseDetailSerializer(serializers.Serializer):
    """``GET /courses/{id}``: shaped from ``selectors.CourseDetail``. Items use the ``/items``
    shape (serializer context needs ``rules``)."""

    course = CourseSummarySerializer(source="enrollment.course", read_only=True)
    is_muted = serializers.BooleanField(source="enrollment.is_muted", read_only=True)
    group_name = serializers.CharField(source="enrollment.group_name", read_only=True)
    tutor_name = serializers.CharField(source="enrollment.tutor_name", read_only=True)
    upcoming_items = ItemSerializer(many=True, read_only=True)
    lecture_schedules = LectureScheduleSerializer(many=True, read_only=True)


class CourseMuteSerializer(serializers.Serializer):
    is_muted = serializers.BooleanField()


class PaginatedItemSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ItemSerializer(many=True)
