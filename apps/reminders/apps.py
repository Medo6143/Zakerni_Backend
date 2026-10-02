from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RemindersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reminders"
    label = "reminders"
    verbose_name = _("Reminders")
