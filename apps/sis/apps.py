from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sis"
    label = "sis"
    verbose_name = _("Student information system")
