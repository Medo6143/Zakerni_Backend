"""In-memory fake Moodle client for tests and local demos.

Fully interchangeable with ``HttpMoodleClient`` (Liskov Substitution): same
protocol, same exceptions, no network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.core.exceptions import InvalidLmsCredentials, LmsTokenExpired, LmsUnavailable
from apps.moodle.protocols import (
    MoodleAssignment,
    MoodleCalendarEvent,
    MoodleCourse,
    MoodleCourseMember,
    MoodleGroup,
    MoodleQuiz,
    SiteInfo,
)


@dataclass
class FakeMoodleClient:
    valid_credentials: dict[str, str] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)  # token -> username
    site_infos: dict[str, SiteInfo] = field(default_factory=dict)  # username -> SiteInfo
    courses_by_user: dict[int, list[MoodleCourse]] = field(default_factory=dict)
    quizzes_by_course: dict[int, list[MoodleQuiz]] = field(default_factory=dict)
    assignments_by_course: dict[int, list[MoodleAssignment]] = field(default_factory=dict)
    # moodle_course_id -> events; key 0 holds the user's own (course-less) events.
    events_by_course: dict[int, list[MoodleCalendarEvent]] = field(default_factory=dict)
    # (moodle_course_id, moodle_user_id) -> groups; group_id -> members.
    groups_by_course_user: dict[tuple[int, int], list[MoodleGroup]] = field(default_factory=dict)
    members_by_group: dict[int, list[MoodleCourseMember]] = field(default_factory=dict)
    # Simulates the site denying the group functions (the real client returns []).
    groups_denied: bool = False
    # Simulates a network failure on the group functions only.
    groups_unavailable: bool = False
    expired_tokens: set[str] = field(default_factory=set)
    unavailable: bool = False

    def add_user(self, username: str, password: str, site_info: SiteInfo, token: str) -> None:
        self.valid_credentials[username] = password
        self.tokens[token] = username
        self.site_infos[username] = site_info

    def expire_token(self, token: str) -> None:
        """Simulate Moodle answering ``invalidtoken`` (e.g. the password changed)."""
        self.expired_tokens.add(token)

    def _check(self, token: str) -> None:
        if self.unavailable:
            raise LmsUnavailable()
        if token in self.expired_tokens:
            raise LmsTokenExpired()

    def get_token(self, username: str, password: str) -> str:
        if self.unavailable:
            raise LmsUnavailable()
        if self.valid_credentials.get(username) != password:
            raise InvalidLmsCredentials()
        for token, user in self.tokens.items():
            if user == username and token not in self.expired_tokens:
                return token
        raise InvalidLmsCredentials()

    def site_info(self, token: str) -> SiteInfo:
        self._check(token)
        username = self.tokens.get(token)
        if username is None or username not in self.site_infos:
            raise LmsTokenExpired()
        return self.site_infos[username]

    def courses(self, token: str, moodle_user_id: int) -> list[MoodleCourse]:
        self._check(token)
        return list(self.courses_by_user.get(moodle_user_id, []))

    def quizzes(self, token: str, course_ids: list[int]) -> list[MoodleQuiz]:
        self._check(token)
        result: list[MoodleQuiz] = []
        for cid in course_ids:
            result.extend(self.quizzes_by_course.get(cid, []))
        return result

    def assignments(self, token: str, course_ids: list[int]) -> list[MoodleAssignment]:
        self._check(token)
        result: list[MoodleAssignment] = []
        for cid in course_ids:
            result.extend(self.assignments_by_course.get(cid, []))
        return result

    def calendar_events(
        self, token: str, course_ids: list[int], time_from: int, time_to: int
    ) -> list[MoodleCalendarEvent]:
        self._check(token)
        result: list[MoodleCalendarEvent] = []
        for cid in [*course_ids, 0]:
            result.extend(
                e
                for e in self.events_by_course.get(cid, [])
                if time_from <= e.time_start <= time_to
            )
        return result

    def course_user_groups(self, token: str, course_id: int, user_id: int) -> list[MoodleGroup]:
        self._check(token)
        if self.groups_unavailable:
            raise LmsUnavailable()
        if self.groups_denied:
            return []
        return list(self.groups_by_course_user.get((course_id, user_id), []))

    def group_members(self, token: str, course_id: int, group_id: int) -> list[MoodleCourseMember]:
        self._check(token)
        if self.groups_denied:
            return []
        return list(self.members_by_group.get(group_id, []))
