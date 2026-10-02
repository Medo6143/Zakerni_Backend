"""Read-only queries for reminder rules and scheduled reminders."""

from __future__ import annotations

import uuid
from datetime import date, datetime, tzinfo
from typing import TYPE_CHECKING

from django.db.models import Count, QuerySet
from django.db.models.functions import TruncDate

from apps.reminders.models import ItemReminderOverride, ReminderRule, ScheduledReminder

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.schedule.models import Item


def reminder_rules_for_user(user: User) -> QuerySet[ReminderRule]:
    return ReminderRule.objects.filter(user=user).order_by("item_type")


def reminder_rules_by_type(user: User) -> dict[str, ReminderRule]:
    return {rule.item_type: rule for rule in reminder_rules_for_user(user)}


def reminder_rule_for(user: User, item_type: str) -> ReminderRule | None:
    return ReminderRule.objects.filter(user=user, item_type=item_type).first()


def override_for_item(item: Item) -> ItemReminderOverride | None:
    return ItemReminderOverride.objects.filter(item=item).first()


def due_reminder_ids(now: datetime, limit: int) -> list[uuid.UUID]:
    return list(
        ScheduledReminder.objects.filter(status=ScheduledReminder.Status.PENDING, send_at__lte=now)
        .order_by("send_at")
        .values_list("id", flat=True)[:limit]
    )


def reminders_for_item(item: Item) -> QuerySet[ScheduledReminder]:
    return ScheduledReminder.objects.filter(item=item).order_by("send_at")


def reminder_count(status: str, since: datetime) -> int:
    """Rows with ``status`` whose send time falls after ``since`` (admin KPIs)."""
    return ScheduledReminder.objects.filter(status=status, send_at__gte=since).count()


def sent_reminders_per_day(since: datetime, zone: tzinfo) -> dict[date, int]:
    rows = (
        ScheduledReminder.objects.filter(status=ScheduledReminder.Status.SENT, sent_at__gte=since)
        .annotate(day=TruncDate("sent_at", tzinfo=zone))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    return {row["day"]: row["total"] for row in rows}
