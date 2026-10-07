"""Strict field types shared by the device-side ingest serializers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

# Anything older than this cannot be a real Moodle / SIS date.
MIN_TIMESTAMP = int(datetime(2015, 1, 1, tzinfo=UTC).timestamp())
MAX_FUTURE_YEARS = 5


def max_timestamp(now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    try:
        return int(moment.replace(year=moment.year + MAX_FUTURE_YEARS).timestamp())
    except ValueError:  # 29 February
        return int(moment.replace(year=moment.year + MAX_FUTURE_YEARS, day=28).timestamp())


class SafeCharField(serializers.CharField):
    """A ``CharField`` that rejects NUL characters (PostgreSQL cannot store them)."""

    def run_validation(self, data: Any = serializers.empty) -> Any:
        if isinstance(data, str) and "\x00" in data:
            raise serializers.ValidationError(_("Invalid characters."))
        return super().run_validation(data)


class UnixTimestampField(serializers.IntegerField):
    """Unix seconds between 2015 and now + 5 years; ``0`` means "no date"."""

    def __init__(self, **kwargs: Any) -> None:
        self.allow_zero = kwargs.pop("allow_zero", True)
        super().__init__(**kwargs)

    def to_internal_value(self, data: Any) -> int:
        value = super().to_internal_value(data)
        if value == 0 and self.allow_zero:
            return 0
        if not MIN_TIMESTAMP <= value <= max_timestamp():
            raise serializers.ValidationError(_("Date out of range."))
        return value


class BoundedListField(serializers.ListField):
    """An optional list with a hard size cap."""

    def __init__(self, *, max_items: int, **kwargs: Any) -> None:
        kwargs.setdefault("required", False)
        super().__init__(max_length=max_items, **kwargs)
