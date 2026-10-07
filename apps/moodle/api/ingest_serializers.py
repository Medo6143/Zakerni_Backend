"""Validation of the ``POST /me/lms/ingest`` body. Field names are the snake_case names of
the dataclasses in ``apps/moodle/protocols.py``."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.core.api.ingest_fields import BoundedListField, SafeCharField, UnixTimestampField
from apps.moodle.protocols import (
    MoodleAssignment,
    MoodleCalendarEvent,
    MoodleCourse,
    MoodleCourseMember,
    MoodleGroup,
    MoodleQuiz,
)
from apps.moodle.services.ingest import LmsIngestData

MAX_COURSES = 200
MAX_GROUPS = 1000
MAX_GROUP_MEMBERS = 5000
MAX_ACTIVITIES = 2000
MAX_EVENTS = 2000
_ID_MAX = 2**31 - 1


def _id() -> serializers.IntegerField:
    return serializers.IntegerField(min_value=1, max_value=_ID_MAX)


class IngestCourseSerializer(serializers.Serializer):
    moodle_course_id = _id()
    code = SafeCharField(max_length=64, allow_blank=True, default="")
    name = SafeCharField(max_length=255, allow_blank=True, default="")
    start_date = UnixTimestampField(default=0)


class IngestGroupSerializer(serializers.Serializer):
    moodle_course_id = _id()
    group_id = _id()
    name = SafeCharField(max_length=255, allow_blank=True)


class IngestGroupMemberSerializer(serializers.Serializer):
    group_id = _id()
    user_id = _id()
    full_name = SafeCharField(max_length=255, allow_blank=True, default="")
    roles = serializers.ListField(
        child=SafeCharField(max_length=64), max_length=20, required=False, default=list
    )


class IngestQuizSerializer(serializers.Serializer):
    moodle_course_id = _id()
    instance_id = _id()
    name = SafeCharField(max_length=255, allow_blank=True)
    time_open = UnixTimestampField(allow_null=True, default=None)
    time_close = UnixTimestampField(allow_null=True, default=None)
    url = SafeCharField(max_length=500, allow_blank=True, default="")


class IngestAssignmentSerializer(serializers.Serializer):
    moodle_course_id = _id()
    instance_id = _id()
    name = SafeCharField(max_length=255, allow_blank=True)
    due_date = UnixTimestampField(allow_null=True, default=None)
    url = SafeCharField(max_length=500, allow_blank=True, default="")
    allow_submissions_from = UnixTimestampField(allow_null=True, default=None)


class IngestCalendarEventSerializer(serializers.Serializer):
    event_id = _id()
    # 0 = an event of the student's own, outside any course.
    moodle_course_id = serializers.IntegerField(min_value=0, max_value=_ID_MAX)
    name = SafeCharField(max_length=255, allow_blank=True)
    time_start = UnixTimestampField(allow_zero=False)
    duration_seconds = serializers.IntegerField(min_value=0, max_value=30 * 86400, default=0)
    description = SafeCharField(max_length=20000, allow_blank=True, default="")
    url = SafeCharField(max_length=500, allow_blank=True, default="")
    module_name = SafeCharField(max_length=64, allow_blank=True, default="")


_LIST_KEYS = ("courses", "groups", "group_members", "quizzes", "assignments", "calendar_events")


class LmsIngestSerializer(serializers.Serializer):
    courses = BoundedListField(max_items=MAX_COURSES, child=IngestCourseSerializer())
    groups = BoundedListField(max_items=MAX_GROUPS, child=IngestGroupSerializer())
    group_members = BoundedListField(
        max_items=MAX_GROUP_MEMBERS, child=IngestGroupMemberSerializer()
    )
    quizzes = BoundedListField(max_items=MAX_ACTIVITIES, child=IngestQuizSerializer())
    assignments = BoundedListField(max_items=MAX_ACTIVITIES, child=IngestAssignmentSerializer())
    calendar_events = BoundedListField(max_items=MAX_EVENTS, child=IngestCalendarEventSerializer())
    lms_status = serializers.ChoiceField(choices=["expired"], required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not any(key in attrs for key in (*_LIST_KEYS, "lms_status")):
            raise serializers.ValidationError(_("Send at least one data list or lms_status."))
        has_items = any(attrs.get(k) for k in ("quizzes", "assignments", "calendar_events"))
        if has_items and not attrs.get("courses") and attrs.get("lms_status") != "expired":
            raise serializers.ValidationError({"courses": _("Courses are required with items.")})
        return attrs


class LmsIngestResultSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="success or failed")
    items_created = serializers.IntegerField()
    items_updated = serializers.IntegerField()
    items_removed = serializers.IntegerField()
    last_synced_at = serializers.DateTimeField(allow_null=True)


def build_ingest_data(validated: dict[str, Any]) -> LmsIngestData:
    """Validated body -> protocol dataclasses (deduplicated by their natural keys)."""
    courses = {
        c["moodle_course_id"]: MoodleCourse(
            moodle_course_id=c["moodle_course_id"],
            code=c["code"],
            name=c["name"],
            start_date=c["start_date"],
        )
        for c in validated.get("courses", [])
    }
    quizzes = {
        q["instance_id"]: MoodleQuiz(
            moodle_course_id=q["moodle_course_id"],
            instance_id=q["instance_id"],
            name=q["name"],
            time_open=q["time_open"],
            time_close=q["time_close"],
            url=q["url"],
        )
        for q in validated.get("quizzes", [])
    }
    assignments = {
        a["instance_id"]: MoodleAssignment(
            moodle_course_id=a["moodle_course_id"],
            instance_id=a["instance_id"],
            name=a["name"],
            due_date=a["due_date"],
            url=a["url"],
            allow_submissions_from=a["allow_submissions_from"],
        )
        for a in validated.get("assignments", [])
    }
    events = {
        e["event_id"]: MoodleCalendarEvent(
            event_id=e["event_id"],
            moodle_course_id=e["moodle_course_id"],
            name=e["name"],
            time_start=e["time_start"],
            duration_seconds=e["duration_seconds"],
            description=e["description"],
            url=e["url"],
            module_name=e["module_name"],
        )
        for e in validated.get("calendar_events", [])
    }
    groups: dict[int, list[MoodleGroup]] = {}
    for g in validated.get("groups", []):
        groups.setdefault(g["moodle_course_id"], []).append(
            MoodleGroup(group_id=g["group_id"], name=g["name"])
        )
    members: dict[int, list[MoodleCourseMember]] = {}
    for m in validated.get("group_members", []):
        members.setdefault(m["group_id"], []).append(
            MoodleCourseMember(
                user_id=m["user_id"], full_name=m["full_name"], roles=tuple(m["roles"])
            )
        )
    return LmsIngestData(
        courses=tuple(courses.values()),
        quizzes=tuple(quizzes.values()),
        assignments=tuple(assignments.values()),
        events=tuple(events.values()),
        groups_by_course=groups,
        members_by_group=members,
        token_expired=validated.get("lms_status") == "expired",
    )
