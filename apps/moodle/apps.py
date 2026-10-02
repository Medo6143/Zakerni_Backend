from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MoodleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.moodle"
    label = "moodle"
    verbose_name = _("Moodle")
