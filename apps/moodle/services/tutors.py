"""Finds a course's group and tutor for one student (part of the Moodle sync).

The tutor is every non-student member of the student's group(s) in the course
(role shortnames such as ``teacher`` or ``editingteacher``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.core.exceptions import LmsTokenExpired, LmsUnavailable
from apps.moodle.protocols import MoodleDataClient

logger = logging.getLogger(__name__)

STUDENT_ROLE = "student"
_MAX_LENGTH = 255


@dataclass(frozen=True)
class CourseTutor:
    group_name: str = ""
    tutor_name: str = ""


def _join(names: list[str]) -> str:
    unique = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    return ", ".join(unique)[:_MAX_LENGTH]


def fetch_course_tutor(
    client: MoodleDataClient, token: str, course_id: int, user_id: int
) -> CourseTutor | None:
    """Never raises. ``None`` means the lookup failed (keep what is stored)."""
    try:
        groups = client.course_user_groups(token, course_id, user_id)
        tutors: list[str] = []
        for group in groups:
            for member in client.group_members(token, course_id, group.group_id):
                if member.user_id != user_id and any(
                    role and role != STUDENT_ROLE for role in member.roles
                ):
                    tutors.append(member.full_name)
    except (LmsUnavailable, LmsTokenExpired):
        logger.warning("tutor lookup failed for moodle course %s", course_id)
        return None
    return CourseTutor(group_name=_join([g.name for g in groups]), tutor_name=_join(tutors))
