"""Validation of the ``POST /me/sis/ingest`` body (``SisScheduleEntry`` field names)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.core.api.ingest_fields import MAX_FUTURE_YEARS, BoundedListField, SafeCharField
from apps.sis.protocols import SisScheduleEntry

MAX_ENTRIES = 2000
_MIN_DAY = date(2015, 1, 1)


class IngestSisEntrySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["lecture", "exam"])
    day = serializers.DateField()
    course_code = SafeCharField(max_length=64)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField(allow_null=True, default=None)
    location_en = SafeCharField(max_length=255, allow_blank=True, default="")
    location_ar = SafeCharField(max_length=255, allow_blank=True, default="")
    lecturer_en = SafeCharField(max_length=255, allow_blank=True, default="")
    lecturer_ar = SafeCharField(max_length=255, allow_blank=True, default="")
    exam_name = SafeCharField(max_length=255, allow_blank=True, default="")
    is_online = serializers.BooleanField(default=False)

    def validate_day(self, value: date) -> date:
        today = datetime.now(UTC).date()
        try:
            latest = today.replace(year=today.year + MAX_FUTURE_YEARS)
        except ValueError:  # 29 February
            latest = today.replace(year=today.year + MAX_FUTURE_YEARS, day=28)
        if not _MIN_DAY <= value <= latest:
            raise serializers.ValidationError(_("Date out of range."))
        return value


class SisIngestSerializer(serializers.Serializer):
    entries = BoundedListField(
        max_items=MAX_ENTRIES, child=IngestSisEntrySerializer(), required=True
    )


class SisIngestResultSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="success or failed")
    items_created = serializers.IntegerField()
    items_updated = serializers.IntegerField()
    items_removed = serializers.IntegerField()
    last_synced_at = serializers.DateTimeField(allow_null=True)


def build_sis_entries(validated: dict[str, Any]) -> tuple[SisScheduleEntry, ...]:
    return tuple(
        SisScheduleEntry(
            kind=e["kind"],
            day=e["day"],
            start_time=e["start_time"],
            end_time=e["end_time"],
            course_code=e["course_code"],
            location_en=e["location_en"],
            location_ar=e["location_ar"],
            lecturer_en=e["lecturer_en"],
            lecturer_ar=e["lecturer_ar"],
            exam_name=e["exam_name"],
            is_online=e["is_online"],
        )
        for e in validated["entries"]
    )
