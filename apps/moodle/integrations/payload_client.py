"""``MoodleDataClient`` backed by data the phone already fetched from Moodle.

In device mode the server never talks to Moodle (Moodle blocks the server's IPs and the
token stays on the phone). The ingest endpoint builds one of these from the validated
payload and hands it to the unchanged ``SyncMoodleAccount``. It is interchangeable with
``HttpMoodleClient`` and ``FakeMoodleClient`` (Liskov Substitution); the ``token``
arguments are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.core.exceptions import LmsTokenExpired
from apps.moodle.protocols import (
    MoodleAssignment,
    MoodleCalendarEvent,
    MoodleCourse,
    MoodleCourseMember,
    MoodleGroup,
    MoodleQuiz,
    SiteInfo,
)


@dataclass(frozen=True)
class PayloadMoodleClient:
    courses_: tuple[MoodleCourse, ...] = ()
    quizzes_: tuple[MoodleQuiz, ...] = ()
    assignments_: tuple[MoodleAssignment, ...] = ()
    events_: tuple[MoodleCalendarEvent, ...] = ()
    # moodle_course_id -> the student's groups in it; group_id -> members.
    groups_by_course: dict[int, list[MoodleGroup]] = field(default_factory=dict)
    members_by_group: dict[int, list[MoodleCourseMember]] = field(default_factory=dict)
    # The phone reported that Moodle rejected its token: behave like ``invalidtoken``.
    token_expired: bool = False

    def _check(self) -> None:
        if self.token_expired:
            raise LmsTokenExpired()

    def site_info(self, token: str) -> SiteInfo:
        raise NotImplementedError("the phone reads site info itself (lms connect)")

    def courses(self, token: str, moodle_user_id: int) -> list[MoodleCourse]:
        self._check()
        return list(self.courses_)

    def quizzes(self, token: str, course_ids: list[int]) -> list[MoodleQuiz]:
        self._check()
        return [q for q in self.quizzes_ if q.moodle_course_id in course_ids]

    def assignments(self, token: str, course_ids: list[int]) -> list[MoodleAssignment]:
        self._check()
        return [a for a in self.assignments_ if a.moodle_course_id in course_ids]

    def calendar_events(
        self, token: str, course_ids: list[int], time_from: int, time_to: int
    ) -> list[MoodleCalendarEvent]:
        self._check()
        # Course 0 holds the user's own (course-less) events.
        wanted = {*course_ids, 0}
        return [
            e
            for e in self.events_
            if e.moodle_course_id in wanted and time_from <= e.time_start <= time_to
        ]

    def course_user_groups(self, token: str, course_id: int, user_id: int) -> list[MoodleGroup]:
        self._check()
        return list(self.groups_by_course.get(course_id, []))

    def group_members(self, token: str, course_id: int, group_id: int) -> list[MoodleCourseMember]:
        self._check()
        return list(self.members_by_group.get(group_id, []))
