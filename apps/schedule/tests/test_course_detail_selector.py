from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.core.exceptions import NotFoundAppError
from apps.schedule.selectors import course_detail_for_user
from apps.schedule.tests.factories import EnrollmentFactory, ItemFactory, MoodleQuizItemFactory

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.django_db


@freeze_time(NOW)
def test_course_detail_selects_next_30_days_of_all_types(user) -> None:
    course = EnrollmentFactory(user=user).course
    quiz = MoodleQuizItemFactory(user=user, course=course, scheduled_at=NOW + timedelta(days=1))
    exam = ItemFactory(user=user, course=course, scheduled_at=NOW + timedelta(days=29))
    ItemFactory(user=user, course=course, scheduled_at=NOW + timedelta(days=31))
    ItemFactory(user=user, course=course, scheduled_at=NOW + timedelta(days=3), deleted_at=NOW)

    detail = course_detail_for_user(user, course.id)

    assert detail.enrollment.course_id == course.id
    assert [i.id for i in detail.upcoming_items] == [quiz.id, exam.id]


def test_course_detail_requires_active_enrollment(user) -> None:
    enrollment = EnrollmentFactory(user=user, is_active=False)

    with pytest.raises(NotFoundAppError):
        course_detail_for_user(user, enrollment.course_id)
