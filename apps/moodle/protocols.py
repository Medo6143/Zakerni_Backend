"""Ports for talking to the university Moodle LMS.

Kept small and separate (Interface Segregation): a service that only needs
a token should not have to depend on the full data-fetching surface, and
vice versa. ``HttpMoodleClient`` implements both for convenience; tests use
``FakeMoodleClient`` which is fully interchangeable (Liskov Substitution).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SiteInfo:
    moodle_user_id: int
    full_name: str
    email: str = ""
    site_url: str = ""


@dataclass(frozen=True)
class MoodleCourse:
    moodle_course_id: int
    code: str
    name: str
    # Unix seconds of the course's ``startdate`` (0 = unknown). AOU reuses course
    # shells across terms, so activities dated before this belong to earlier terms.
    start_date: int = 0


@dataclass(frozen=True)
class MoodleQuiz:
    moodle_course_id: int
    instance_id: int
    name: str
    time_open: int | None
    time_close: int | None
    url: str = ""


@dataclass(frozen=True)
class MoodleAssignment:
    moodle_course_id: int
    instance_id: int
    name: str
    due_date: int | None
    url: str = ""
    allow_submissions_from: int | None = None


@dataclass(frozen=True)
class MoodleAnnouncement:
    """A post of a course's "news" forum (posted by the phone, never fetched by the
    server). ``message`` is raw HTML or text; ``group_id`` 0 means every group."""

    moodle_course_id: int
    forum_id: int
    discussion_id: int
    subject: str
    message: str
    time_created: int
    time_modified: int
    group_id: int = 0
    author_name: str = ""
    pinned: bool = False
    url: str = ""


@dataclass(frozen=True)
class MoodleCalendarEvent:
    """A Moodle calendar event. ``module_name`` is empty for plain course/user/group
    events (e.g. a Teams lecture) and set (``quiz``, ``assign``) for activity events.
    ``description`` is the raw HTML from Moodle."""

    event_id: int
    moodle_course_id: int
    name: str
    time_start: int
    duration_seconds: int = 0
    description: str = ""
    url: str = ""
    module_name: str = ""


@dataclass(frozen=True)
class MoodleGroup:
    group_id: int
    name: str


@dataclass(frozen=True)
class MoodleCourseMember:
    """An enrolled user of a course with their role shortnames (``student``, ``teacher``...)."""

    user_id: int
    full_name: str
    roles: tuple[str, ...] = ()


class MoodleAuthClient(Protocol):
    def get_token(self, username: str, password: str) -> str:
        """Exchange LMS credentials for a Moodle web-service token.

        Raises ``InvalidLmsCredentials`` or ``LmsUnavailable``. The
        password must never be persisted or logged past this call.
        """
        ...


class MoodleSiteClient(Protocol):
    """Login-time lookup of the signed-in user (only the server-side login flow needs it)."""

    def site_info(self, token: str) -> SiteInfo: ...


class MoodleDataClient(Protocol):
    """All methods raise ``LmsTokenExpired`` when Moodle answers ``invalidtoken``
    and ``LmsUnavailable`` for network/server failures. Timestamps are Unix seconds."""

    def courses(self, token: str, moodle_user_id: int) -> list[MoodleCourse]:
        """Current-term courses only (Moodle "In progress"), never past or future ones."""
        ...

    def quizzes(self, token: str, course_ids: list[int]) -> list[MoodleQuiz]: ...

    def assignments(self, token: str, course_ids: list[int]) -> list[MoodleAssignment]: ...

    def calendar_events(
        self, token: str, course_ids: list[int], time_from: int, time_to: int
    ) -> list[MoodleCalendarEvent]:
        """Calendar events of these courses (plus the user's own events) starting in
        ``[time_from, time_to]``. Activity events are returned too; the sync ignores them."""
        ...

    def course_user_groups(self, token: str, course_id: int, user_id: int) -> list[MoodleGroup]:
        """The user's groups in this course. Returns ``[]`` when the site denies it."""
        ...

    def group_members(self, token: str, course_id: int, group_id: int) -> list[MoodleCourseMember]:
        """Enrolled users of one group (at most 200). Returns ``[]`` when the site denies it."""
        ...
