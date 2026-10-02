"""Unfold admin dashboard (``UNFOLD["DASHBOARD_CALLBACK"]``).

Reads only through selectors: KPI cards, reminders sent per day (14 days) and
the last 10 failed Moodle syncs (docs/06-screens-and-flows.md, Admin).
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import HttpRequest
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from apps.accounts.selectors import students_count
from apps.moodle.selectors import recent_failed_syncs
from apps.notifications.selectors import active_devices_count, telegram_linked_users_count
from apps.reminders.models import ScheduledReminder
from apps.reminders.selectors import reminder_count, sent_reminders_per_day
from apps.support.selectors import open_reports_count

CHART_DAYS = 14


def _kpis(now: Any) -> list[dict[str, Any]]:
    since = now - timedelta(hours=24)
    return [
        {"title": _("Users"), "value": students_count(), "icon": "group"},
        {"title": _("Active devices"), "value": active_devices_count(), "icon": "smartphone"},
        {
            "title": _("Telegram-linked users"),
            "value": telegram_linked_users_count(),
            "icon": "send",
        },
        {
            "title": _("Reminders sent (24 h)"),
            "value": reminder_count(ScheduledReminder.Status.SENT, since),
            "icon": "notifications_active",
        },
        {
            "title": _("Reminders failed (24 h)"),
            "value": reminder_count(ScheduledReminder.Status.FAILED, since),
            "icon": "error",
        },
        {"title": _("Open reports"), "value": open_reports_count(), "icon": "support_agent"},
    ]


def _chart(now: Any) -> str:
    zone = ZoneInfo(settings.DEFAULT_TIMEZONE)
    today = now.astimezone(zone).date()
    days = [today - timedelta(days=offset) for offset in range(CHART_DAYS - 1, -1, -1)]
    start = datetime.combine(days[0], time.min, tzinfo=zone)
    counts = sent_reminders_per_day(start, zone)
    return json.dumps(
        {
            "labels": [formats.date_format(day, "M j") for day in days],
            "datasets": [
                {
                    "label": _("Reminders sent"),
                    "data": [counts.get(day, 0) for day in days],
                    "backgroundColor": "#4F46E5",
                }
            ],
        }
    )


def _failed_syncs() -> dict[str, Any]:
    rows = []
    for log in recent_failed_syncs(10):
        rows.append(
            [
                log.moodle_account.user.moodle_username,
                formats.date_format(timezone.localtime(log.started_at), "DATETIME_FORMAT"),
                log.error or "-",
            ]
        )
    return {"headers": [_("User"), _("Started at"), _("Error")], "rows": rows}


def dashboard_callback(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    now = timezone.now()
    context.update(
        {
            "zakerni_kpis": _kpis(now),
            "zakerni_chart": _chart(now),
            "zakerni_failed_syncs": _failed_syncs(),
        }
    )
    return context
