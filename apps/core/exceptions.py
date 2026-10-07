"""Domain-level application errors.

Services raise these instead of DRF exceptions so that the same error type
can be reused from Celery tasks and management commands. The DRF exception
handler (``apps.core.api.exceptions``) converts them into the standard
error envelope.
"""

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _


class ApplicationError(Exception):
    code: str = "application_error"
    status: int = 400
    message: str | Promise = _("Something went wrong.")

    def __init__(self, message: str | None = None, details: dict | None = None) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class ValidationAppError(ApplicationError):
    code = "validation_error"
    status = 400
    message = _("Invalid input.")


class InvalidLmsCredentials(ApplicationError):
    code = "invalid_lms_credentials"
    status = 401
    message = _("Incorrect username or password.")


class LmsUnavailable(ApplicationError):
    code = "lms_unavailable"
    status = 503
    message = _("The university system is currently unavailable. Please try again later.")


class LmsTokenExpired(ApplicationError):
    code = "lms_token_expired"
    status = 401
    message = _("Your university session has expired. Please log in again.")


class TelegramLinkExpired(ApplicationError):
    code = "telegram_link_expired"
    status = 400
    message = _("This Telegram link has expired. Please request a new one.")


class TelegramNotLinked(ApplicationError):
    code = "telegram_not_linked"
    status = 400
    message = _("Link your Telegram account first.")


class ItemNotEditable(ApplicationError):
    code = "item_not_editable"
    status = 400
    message = _("This item comes from the university system and cannot be edited.")


class NotFoundAppError(ApplicationError):
    code = "not_found"
    status = 404
    message = _("Not found.")


class ThrottledAppError(ApplicationError):
    code = "throttled"
    status = 429
    message = _("Too many requests. Please try again later.")


class DeviceMismatch(ApplicationError):
    code = "device_mismatch"
    status = 403
    message = _("This account is linked to another device. Contact support to reset it.")


class SisInvalidCredentials(ApplicationError):
    # 400, not 401: a 401 would make the app try to refresh its own JWT.
    code = "sis_invalid_credentials"
    status = 400
    message = _("Incorrect SIS username or password.")


class SisUnavailable(ApplicationError):
    code = "sis_unavailable"
    status = 503
    message = _("The student information system is currently unavailable. Please try again later.")
