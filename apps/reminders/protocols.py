"""Port used by other apps to (re)schedule reminders without knowing how."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid

    from apps.accounts.models import User
    from apps.schedule.models import Item


class ReminderScheduler(Protocol):
    def schedule_for_item(self, item: Item) -> None:
        """Bring the item's pending reminders in line with rules/overrides/mutes."""
        ...

    def cancel_for_item(self, item: Item) -> None:
        """Cancel every pending reminder of the item."""
        ...

    def reschedule_for_user(
        self,
        user: User,
        *,
        item_type: str | None = None,
        course_id: uuid.UUID | None = None,
    ) -> int:
        """Reschedule all upcoming items of the user (optionally filtered). Returns the count."""
        ...
