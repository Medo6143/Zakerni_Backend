from apps.moodle.integrations.fake_client import FakeMoodleClient
from apps.moodle.protocols import MoodleCourseMember, MoodleGroup
from apps.moodle.services.tutors import CourseTutor, fetch_course_tutor


def test_tutors_are_non_student_members_across_groups() -> None:
    moodle = FakeMoodleClient()
    moodle.groups_by_course_user[(1, 7)] = [
        MoodleGroup(group_id=10, name="28"),
        MoodleGroup(group_id=11, name="29"),
    ]
    moodle.members_by_group[10] = [
        MoodleCourseMember(user_id=7, full_name="Me", roles=("student",)),
        MoodleCourseMember(user_id=8, full_name="Dr. A", roles=("editingteacher", "student")),
    ]
    moodle.members_by_group[11] = [
        MoodleCourseMember(user_id=8, full_name="Dr. A", roles=("editingteacher",)),
        MoodleCourseMember(user_id=9, full_name="Dr. B", roles=("teacher",)),
    ]

    assert fetch_course_tutor(moodle, "t", 1, 7) == CourseTutor(
        group_name="28, 29", tutor_name="Dr. A, Dr. B"
    )


def test_no_groups_means_blank() -> None:
    assert fetch_course_tutor(FakeMoodleClient(), "t", 1, 7) == CourseTutor()


def test_network_failure_returns_none() -> None:
    moodle = FakeMoodleClient(groups_unavailable=True)

    assert fetch_course_tutor(moodle, "t", 1, 7) is None
