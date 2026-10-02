from datetime import UTC, datetime

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.notifications.channels.telegram import format_telegram_text
from apps.reminders.services.messages import render_reminder_message
from apps.schedule.tests.factories import CourseFactory, EnrollmentFactory, ItemFactory

# 1 Oct 2026 19:00 UTC = 22:00 in Cairo (UTC+3, Egypt summer time).
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
CLOSE = datetime(2026, 10, 1, 19, 0, tzinfo=UTC)

pytestmark = pytest.mark.django_db


def _quiz(user):  # type: ignore[no-untyped-def]
    course = CourseFactory(code="M110")
    return ItemFactory(
        user=user, type="quiz", source="moodle", title="Quiz 2", course=course, scheduled_at=CLOSE
    )


def test_english_message() -> None:
    user = UserFactory(language="en", timezone="Africa/Cairo")

    message = render_reminder_message(_quiz(user), user=user, now=NOW)

    assert message.title == "Quiz reminder"
    assert message.body == "M110 — Quiz 2 closes tomorrow at 10:00 PM"


def test_arabic_message() -> None:
    user = UserFactory(language="ar", timezone="Africa/Cairo")

    message = render_reminder_message(_quiz(user), user=user, now=NOW)

    assert message.title == "تذكير بكويز"
    assert message.body == "كويز M110 — Quiz 2 بيقفل بكرة الساعة 10:00 م"


def test_today_and_other_dates_and_timezone() -> None:
    user = UserFactory(language="en", timezone="UTC")
    item = _quiz(user)

    same_day = render_reminder_message(item, user=user, now=datetime(2026, 10, 1, 8, 0, tzinfo=UTC))
    later = render_reminder_message(item, user=user, now=datetime(2026, 9, 25, 8, 0, tzinfo=UTC))

    assert same_day.body.endswith("closes today at 7:00 PM")
    assert later.body.endswith("closes on Thu 1 Oct at 7:00 PM")


def test_invalid_timezone_falls_back_to_default() -> None:
    user = UserFactory(language="en", timezone="Mars/Olympus")

    message = render_reminder_message(_quiz(user), user=user, now=NOW)

    assert message.body.endswith("tomorrow at 10:00 PM")


@pytest.mark.parametrize(
    ("item_type", "verb"),
    [("tma", "is due"), ("exam", "starts"), ("lecture", "starts")],
)
def test_every_type_has_a_phrase(item_type, verb) -> None:
    user = UserFactory(language="en")
    source = "moodle" if item_type == "tma" else "manual"
    item = ItemFactory(user=user, type=item_type, source=source, title="X", scheduled_at=CLOSE)

    message = render_reminder_message(item, user=user, now=NOW)

    assert message.body.startswith(f"X {verb} ")


def test_body_and_long_body_without_location_or_tutor() -> None:
    user = UserFactory(language="en", timezone="Africa/Cairo")

    message = render_reminder_message(_quiz(user), user=user, now=NOW)

    assert message.long_body == message.body


def test_location_and_tutor_in_english() -> None:
    user = UserFactory(language="en", timezone="Africa/Cairo")
    item = _quiz(user)
    item.location = "Hall 3"
    EnrollmentFactory(user=user, course=item.course, tutor_name="Dr. Ahmed")

    message = render_reminder_message(item, user=user, now=NOW)

    assert message.body == "M110 — Quiz 2 closes tomorrow at 10:00 PM\nHall 3"
    assert message.long_body == (
        "M110 — Quiz 2 closes tomorrow at 10:00 PM\nLocation: Hall 3\nTutor: Dr. Ahmed"
    )
    assert format_telegram_text(message) == f"Quiz reminder\n{message.long_body}"


def test_teams_lecture_in_arabic() -> None:
    user = UserFactory(language="ar", timezone="Africa/Cairo")
    course = CourseFactory(code="M110")
    EnrollmentFactory(user=user, course=course, tutor_name="د. منى")
    link = "https://teams.microsoft.com/l/meetup-join/abc"
    item = ItemFactory(
        user=user,
        type="lecture",
        source="moodle",
        title="Lecture 4",
        course=course,
        url=link,
        scheduled_at=CLOSE,
    )

    message = render_reminder_message(item, user=user, now=NOW)

    assert message.body.endswith("\nأونلاين (Teams)")
    lines = message.long_body.split("\n")
    assert lines[1:] == ["المكان: أونلاين (Teams)", "الدكتور: د. منى", f"رابط الدخول: {link}"]
    assert link not in message.body
