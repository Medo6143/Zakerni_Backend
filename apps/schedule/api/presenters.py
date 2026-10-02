"""Builds ``Item`` API payloads (reads through selectors, shapes through serializers).
Shared by the schedule and reminders views."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from apps.reminders.selectors import reminder_rules_by_type
from apps.schedule.api.serializers import CourseDetailSerializer, ItemSerializer
from apps.schedule.models import Item
from apps.schedule.selectors import course_detail_for_user, item_for_user


def item_payload(user: Any, item_id: uuid.UUID) -> dict:
    item = item_for_user(user, item_id)
    return ItemSerializer(item, context={"rules": reminder_rules_by_type(user)}).data


def items_payload(user: Any, items: Iterable[Item]) -> list:
    return ItemSerializer(items, many=True, context={"rules": reminder_rules_by_type(user)}).data


def course_detail_payload(user: Any, course_id: uuid.UUID) -> dict:
    detail = course_detail_for_user(user, course_id)
    return CourseDetailSerializer(detail, context={"rules": reminder_rules_by_type(user)}).data
