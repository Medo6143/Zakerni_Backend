from apps.accounts.models import User


def user_by_moodle_username(moodle_username: str) -> User | None:
    return User.objects.filter(moodle_username=moodle_username).first()


def students_count() -> int:
    return User.objects.filter(is_staff=False, is_active=True).count()
