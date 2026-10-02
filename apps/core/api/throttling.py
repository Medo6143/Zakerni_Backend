"""Throttles that accept multi-unit periods such as ``1/5m`` (DRF only reads the
first letter of the period, so ``5min`` would silently mean one minute)."""

from __future__ import annotations

import re

from rest_framework.throttling import UserRateThrottle

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_PERIOD = re.compile(r"^(\d*)\s*([smhd])[a-z]*$")


class FlexibleRateMixin:
    def parse_rate(self, rate: str | None) -> tuple[int | None, int | None]:
        if rate is None:
            return (None, None)
        num, period = rate.split("/")
        match = _PERIOD.match(period.strip().lower())
        if match is None:
            raise ValueError(f"Invalid throttle rate: {rate}")
        multiplier = int(match.group(1) or 1)
        return int(num), multiplier * _UNITS[match.group(2)]


class LmsSyncThrottle(FlexibleRateMixin, UserRateThrottle):
    scope = "lms_sync"


class ReportCreateThrottle(FlexibleRateMixin, UserRateThrottle):
    scope = "report_create"


class SisSyncThrottle(FlexibleRateMixin, UserRateThrottle):
    scope = "sis_sync"
