"""Per-course mute."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.schedule.models import Enrollment

if TYPE_CHECKING:
    from apps.reminders.protocols import ReminderScheduler


def set_course_muted(
    enrollment: Enrollment, *, is_muted: bool, scheduler: ReminderScheduler
) -> Enrollment:
    if enrollment.is_muted != is_muted:
        enrollment.is_muted = is_muted
        enrollment.save(update_fields=["is_muted", "updated_at"])
    scheduler.reschedule_for_user(enrollment.user, course_id=enrollment.course_id)
    return enrollment
