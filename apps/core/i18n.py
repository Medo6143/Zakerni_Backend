"""Helpers for rendering server-side text in a given user's language."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import translation

SUPPORTED_LANGUAGES = {code for code, _name in settings.LANGUAGES}


def normalise_language(language: str | None) -> str:
    return language if language in SUPPORTED_LANGUAGES else "ar"


def render_in(language: str | None, text: Any, **params: Any) -> str:
    """Render a lazy translatable string (optionally %-formatted) in ``language``."""
    with translation.override(normalise_language(language)):
        rendered = str(text)
        return rendered % params if params else rendered
