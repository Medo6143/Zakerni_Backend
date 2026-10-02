from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.schedule.models import Course, Enrollment, Item, ItemSource, ItemType


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    moodle_course_id = factory.Sequence(lambda n: 1000 + n)
    code = factory.Sequence(lambda n: f"M{110 + n}")
    name = factory.Sequence(lambda n: f"Course {n}")


class EnrollmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Enrollment

    user = factory.SubFactory(UserFactory)
    course = factory.SubFactory(CourseFactory)


class ItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Item

    user = factory.SubFactory(UserFactory)
    type = ItemType.EXAM
    source = ItemSource.MANUAL
    title = factory.Sequence(lambda n: f"Item {n}")
    scheduled_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=10))


class MoodleQuizItemFactory(ItemFactory):
    type = ItemType.QUIZ
    source = ItemSource.MOODLE
    external_id = factory.Sequence(lambda n: str(500 + n))
