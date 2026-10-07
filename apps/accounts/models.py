from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import UUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, moodle_username: str, password: str | None, **extra_fields):
        if not moodle_username:
            raise ValueError("moodle_username is required")
        user = self.model(moodle_username=moodle_username, **extra_fields)
        user.set_password(password)  # type: ignore[attr-defined]
        user.save(using=self._db)
        return user

    def create_user(self, moodle_username: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(moodle_username, password, **extra_fields)

    def create_superuser(self, moodle_username: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        return self._create_user(moodle_username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, UUIDModel):
    """Zakerni student (or staff) account.

    Students have their own app account (``moodle_username`` holds the student number,
    ``password`` is a hashed app password). Legacy accounts created by the server-side
    LMS login have an unusable password. Connecting the LMS is optional (``MoodleAccount``).
    """

    class Language(models.TextChoices):
        AR = "ar", _("Arabic")
        EN = "en", _("English")

    moodle_username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.AR)
    timezone = models.CharField(max_length=64, default="Africa/Cairo")
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    # Onboarding step 7 ("Default reminders" -> Continue). Null until confirmed.
    reminder_defaults_confirmed_at = models.DateTimeField(
        _("reminder defaults confirmed at"), null=True, blank=True
    )

    objects = UserManager()

    USERNAME_FIELD = "moodle_username"
    REQUIRED_FIELDS: list[str] = []  # type: ignore[misc]

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return self.full_name or self.moodle_username
