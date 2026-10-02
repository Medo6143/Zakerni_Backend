"""DRF exception handler producing the Zakerni error envelope.

{"error": {"code": "...", "message": "<translated>", "details": {...}}}
"""

from __future__ import annotations

from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.exceptions import ApplicationError, NotFoundAppError, ValidationAppError


def zakerni_exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, ApplicationError):
        return Response(
            {"error": {"code": exc.code, "message": str(exc.message), "details": exc.details}},
            status=exc.status,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, drf_exceptions.ValidationError):
        code = "validation_error"
        details = response.data if isinstance(response.data, dict) else {"detail": response.data}
        message = str(ValidationAppError.message)
    elif isinstance(exc, drf_exceptions.Throttled):
        code = "throttled"
        details = {}
        message = str(exc.detail)
    elif isinstance(exc, drf_exceptions.AuthenticationFailed | drf_exceptions.NotAuthenticated):
        code = "authentication_failed"
        details = {}
        message = str(exc.detail)
    elif isinstance(exc, drf_exceptions.PermissionDenied):
        code = "permission_denied"
        details = {}
        message = str(exc.detail)
    elif isinstance(exc, drf_exceptions.NotFound | Http404):
        code = "not_found"
        details = {}
        message = str(NotFoundAppError.message)
    elif isinstance(exc, drf_exceptions.MethodNotAllowed):
        code = "method_not_allowed"
        details = {}
        message = str(exc.detail)
    elif isinstance(exc, drf_exceptions.UnsupportedMediaType | drf_exceptions.ParseError):
        code = "bad_request"
        details = {}
        message = str(exc.detail)
    else:
        code = "error"
        details = response.data if isinstance(response.data, dict) else {"detail": response.data}
        message = str(ApplicationError.message)

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
