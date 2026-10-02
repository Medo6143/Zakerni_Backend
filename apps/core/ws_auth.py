"""WebSocket authentication (docs/05, "Real-time report chat").

- Mobile: ``?token=<JWT access token>`` in the query string. A token that is present but
  invalid, expired or belongs to an inactive user leaves the connection anonymous, and
  the consumer closes it with ``4401``.
- Admin: no ``token``; the Django session cookie is used (``AuthMiddlewareStack``), but
  only when the ``Origin`` header matches ``ALLOWED_HOSTS``, so another site cannot
  ride on a staff member's cookie.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http.request import validate_host
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


@database_sync_to_async
def _user_for_token(raw_token: str) -> Any:
    auth = JWTAuthentication()
    try:
        return auth.get_user(auth.get_validated_token(raw_token.encode()))
    except (InvalidToken, TokenError, AuthenticationFailed):
        return AnonymousUser()


def _header(scope: dict, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def _origin_allowed(scope: dict) -> bool:
    origin = _header(scope, b"origin")
    if not origin:
        return False
    host = urlsplit(origin).hostname or ""
    return validate_host(host, settings.ALLOWED_HOSTS)


class JwtOrSessionAuthMiddleware:
    """Runs inside ``AuthMiddlewareStack`` so ``scope["user"]`` already holds the session
    user; a query-string token replaces it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def __call__(self, scope: dict, receive: Any, send: Any) -> Any:
        query = parse_qs(scope.get("query_string", b"").decode())
        tokens = query.get("token")
        if tokens:
            scope = {**scope, "user": await _user_for_token(tokens[0])}
        elif not _origin_allowed(scope):
            scope = {**scope, "user": AnonymousUser()}
        return await self.inner(scope, receive, send)


def WebSocketAuthStack(inner: Any) -> Any:  # noqa: N802 - mirrors AuthMiddlewareStack
    return AuthMiddlewareStack(JwtOrSessionAuthMiddleware(inner))
