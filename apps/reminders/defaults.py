"""Single registry of default reminder rules per item type (Open/Closed).

A new item type = a new ``ItemType`` value + one entry here (+ its message
phrase in ``services/messages.py``). Nothing else branches on the type.
Values match ``docs/00-overview.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.notifications.models import Channel
from apps.schedule.models import ItemType

# Validation limits (docs/04-erd.md check constraints, docs/05-api-spec.md).
OFFSET_MIN_MINUTES = 5
OFFSET_MAX_MINUTES = 20160  # 14 days
MAX_OFFSETS = 5


@dataclass(frozen=True)
class RuleDefault:
    offsets: tuple[int, ...]
    channels: frozenset[str]


_PUSH_AND_TELEGRAM = frozenset({Channel.PUSH.value, Channel.TELEGRAM.value})
_PUSH_ONLY = frozenset({Channel.PUSH.value})

DEFAULT_RULES: dict[str, RuleDefault] = {
    ItemType.QUIZ.value: RuleDefault(offsets=(1440, 180), channels=_PUSH_AND_TELEGRAM),
    ItemType.TMA.value: RuleDefault(offsets=(4320, 1440), channels=_PUSH_AND_TELEGRAM),
    ItemType.EXAM.value: RuleDefault(offsets=(4320, 1440), channels=_PUSH_AND_TELEGRAM),
    ItemType.LECTURE.value: RuleDefault(offsets=(30,), channels=_PUSH_ONLY),
}
