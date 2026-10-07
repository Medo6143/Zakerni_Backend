"""Concrete Moodle client using the Moodle mobile web-service REST API.

Implements both ``MoodleAuthClient`` and ``MoodleDataClient``. All calls go
through ``httpx`` with a 10s timeout and a small retry budget for transient
network failures, per CLAUDE.md section 5.
"""

from __future__ import annotations

import logging
import time

import httpx
from django.conf import settings

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

logger = logging.getLogger(__name__)

_RETRIABLE_STATUS = {502, 503, 504}
_TOKEN_ERRORS = {"invalidtoken", "accessexception"}


class _FunctionUnavailable(Exception):
    """The site answered a web-service exception other than ``invalidtoken`` for an
    optional function (e.g. it is not enabled for the service): use a fallback."""


class HttpMoodleClient:
    def __init__(self, base_url: str, service_name: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_name = service_name
        self._timeout = timeout

    @classmethod
    def from_settings(cls) -> HttpMoodleClient:
        return cls(
            base_url=settings.MOODLE_BASE_URL,
            service_name=settings.MOODLE_SERVICE_NAME,
            timeout=settings.MOODLE_HTTP_TIMEOUT_SECONDS,
        )

    def _request(self, params: dict, *, optional: bool = False) -> dict:
        url = f"{self._base_url}/webservice/rest/server.php"
        params = {**params, "moodlewsrestformat": "json"}
        attempts = 0
        last_exc: Exception | None = None
        while attempts < 3:
            attempts += 1
            try:
                response = httpx.get(url, params=params, timeout=self._timeout)
            except httpx.TimeoutException as exc:
                last_exc = exc
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if response.status_code in _RETRIABLE_STATUS:
                last_exc = RuntimeError(f"Moodle returned {response.status_code}")
                continue
            if response.status_code >= 400:
                raise LmsUnavailable()
            try:
                data = response.json()
            except ValueError as exc:
                raise LmsUnavailable() from exc
            if isinstance(data, dict) and "exception" in data:
                # Moodle reports web-service errors with HTTP 200 + an exception body.
                if optional and data.get("errorcode") != "invalidtoken":
                    raise _FunctionUnavailable(str(data.get("errorcode", "")))
                if data.get("errorcode") in _TOKEN_ERRORS:
                    raise LmsTokenExpired()
                raise LmsUnavailable(details={"moodle_error": str(data.get("errorcode", ""))})
            return data
        raise LmsUnavailable() from last_exc

    def get_token(self, username: str, password: str) -> str:
        url = f"{self._base_url}/login/token.php"
        try:
            response = httpx.get(
                url,
                params={
                    "username": username,
                    "password": password,
                    "service": self._service_name,
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise LmsUnavailable() from exc

        if response.status_code >= 500:
            raise LmsUnavailable()

        try:
            data = response.json()
        except ValueError as exc:
            # Never log the URL: its query string holds the password.
            logger.warning(
                "Moodle token endpoint returned non-JSON: HTTP %s, content-type %r, %d bytes",
                response.status_code,
                response.headers.get("content-type", ""),
                len(response.content),
            )
            raise LmsUnavailable(details={"moodle_error": "non_json_response"}) from exc
        if not isinstance(data, dict):
            raise LmsUnavailable(details={"moodle_error": "unexpected_response"})
        if "token" not in data:
            error_code = data.get("errorcode", "")
            if error_code in {"invalidlogin", "missingusername", "missingpassword"}:
                raise InvalidLmsCredentials()
            raise LmsUnavailable(details={"moodle_error": error_code})
        return data["token"]

    def site_info(self, token: str) -> SiteInfo:
        data = self._request({"wstoken": token, "wsfunction": "core_webservice_get_site_info"})
        return SiteInfo(
            moodle_user_id=data["userid"],
            full_name=data.get("fullname", ""),
            email=data.get("useremail", ""),
            site_url=data.get("siteurl", self._base_url),
        )

    def courses(self, token: str, moodle_user_id: int) -> list[MoodleCourse]:
        """Current-term courses: the "In progress" timeline classification. If the site
        does not expose that function to the service, fall back to every enrolment
        filtered by course dates (started, not ended, not hidden)."""
        try:
            data = self._request(
                {
                    "wstoken": token,
                    "wsfunction": "core_course_get_enrolled_courses_by_timeline_classification",
                    "classification": "inprogress",
                    "limit": 0,
                    "offset": 0,
                },
                optional=True,
            )
        except _FunctionUnavailable:
            data = self._request(
                {
                    "wstoken": token,
                    "wsfunction": "core_enrol_get_users_courses",
                    "userid": moodle_user_id,
                }
            )
            courses: list[dict] = data if isinstance(data, list) else []
            return [self._course(c) for c in filter_current_courses(courses, int(time.time()))]
        return [self._course(c) for c in data.get("courses", []) if not c.get("hidden")]

    @staticmethod
    def _course(raw: dict) -> MoodleCourse:
        return MoodleCourse(
            moodle_course_id=raw["id"],
            code=raw.get("shortname", ""),
            name=raw.get("fullname", ""),
            start_date=int(raw.get("startdate") or 0),
        )

    def calendar_events(
        self, token: str, course_ids: list[int], time_from: int, time_to: int
    ) -> list[MoodleCalendarEvent]:
        params: dict = {
            "wstoken": token,
            "wsfunction": "core_calendar_get_calendar_events",
            "options[userevents]": 1,
            "options[siteevents]": 0,
            "options[timestart]": time_from,
            "options[timeend]": time_to,
        }
        for i, cid in enumerate(course_ids):
            params[f"events[courseids][{i}]"] = cid
        data = self._request(params)
        return [
            MoodleCalendarEvent(
                event_id=e["id"],
                moodle_course_id=e.get("courseid") or 0,
                name=e.get("name", ""),
                time_start=e.get("timestart") or 0,
                duration_seconds=e.get("timeduration") or 0,
                description=e.get("description") or "",
                url=e.get("url") or "",
                module_name=e.get("modulename") or "",
            )
            for e in data.get("events", [])
            if e.get("timestart")
        ]

    def quizzes(self, token: str, course_ids: list[int]) -> list[MoodleQuiz]:
        if not course_ids:
            return []
        params: dict = {"wstoken": token, "wsfunction": "mod_quiz_get_quizzes_by_courses"}
        for i, cid in enumerate(course_ids):
            params[f"courseids[{i}]"] = cid
        data = self._request(params)
        return [
            MoodleQuiz(
                moodle_course_id=q["course"],
                instance_id=q["id"],
                name=q.get("name", ""),
                time_open=q.get("timeopen") or None,
                time_close=q.get("timeclose") or None,
                url=self._activity_url("quiz", q.get("coursemodule")),
            )
            for q in data.get("quizzes", [])
        ]

    def _activity_url(self, module: str, course_module_id: int | None) -> str:
        if not course_module_id:
            return ""
        return f"{self._base_url}/mod/{module}/view.php?id={course_module_id}"

    def assignments(self, token: str, course_ids: list[int]) -> list[MoodleAssignment]:
        if not course_ids:
            return []
        params: dict = {"wstoken": token, "wsfunction": "mod_assign_get_assignments"}
        for i, cid in enumerate(course_ids):
            params[f"courseids[{i}]"] = cid
        data = self._request(params)
        assignments = []
        for course in data.get("courses", []):
            for a in course.get("assignments", []):
                assignments.append(
                    MoodleAssignment(
                        moodle_course_id=course["id"],
                        instance_id=a["id"],
                        name=a.get("name", ""),
                        due_date=a.get("duedate") or None,
                        url=self._activity_url("assign", a.get("cmid")),
                        allow_submissions_from=a.get("allowsubmissionsfromdate") or None,
                    )
                )
        return assignments

    def course_user_groups(self, token: str, course_id: int, user_id: int) -> list[MoodleGroup]:
        try:
            data = self._request(
                {
                    "wstoken": token,
                    "wsfunction": "core_group_get_course_user_groups",
                    "courseid": course_id,
                    "userid": user_id,
                },
                optional=True,
            )
        except _FunctionUnavailable:
            return []
        groups = data.get("groups", []) if isinstance(data, dict) else []
        return [
            MoodleGroup(group_id=g["id"], name=g.get("name", "")) for g in groups if g.get("id")
        ]

    def group_members(self, token: str, course_id: int, group_id: int) -> list[MoodleCourseMember]:
        try:
            data = self._request(
                {
                    "wstoken": token,
                    "wsfunction": "core_enrol_get_enrolled_users",
                    "courseid": course_id,
                    "options[0][name]": "groupid",
                    "options[0][value]": group_id,
                    "options[1][name]": "limitnumber",
                    "options[1][value]": 200,
                },
                optional=True,
            )
        except _FunctionUnavailable:
            return []
        users: list[dict] = data if isinstance(data, list) else []
        return [
            MoodleCourseMember(
                user_id=u["id"],
                full_name=u.get("fullname", ""),
                roles=tuple(r.get("shortname", "") for r in u.get("roles") or []),
            )
            for u in users
            if u.get("id")
        ]


def filter_current_courses(courses: list[dict], now: int) -> list[dict]:
    """Keep visible courses where ``startdate <= now`` and ``enddate`` is 0 or later."""
    return [
        c
        for c in courses
        if c.get("visible", 1)
        and not c.get("hidden")
        and (c.get("startdate") or 0) <= now
        and (not c.get("enddate") or c["enddate"] >= now)
    ]
