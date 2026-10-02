"""``PushSender`` backed by firebase-admin.

The Firebase app is initialised lazily on the first send, from the
service-account JSON at ``FIREBASE_CREDENTIALS_FILE``, with a 10s HTTP timeout.
Every expected failure is mapped to a ``PushResult``; nothing is raised.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from django.conf import settings

from apps.notifications.protocols import Message, PushResult

logger = logging.getLogger(__name__)

_APP_NAME = "zakerni"
_lock = threading.Lock()


class FirebasePushSender:
    def __init__(self, credentials_file: str, timeout: float = 10.0) -> None:
        self._credentials_file = credentials_file
        self._timeout = timeout
        self._app: Any = None

    @classmethod
    def from_settings(cls) -> FirebasePushSender:
        return cls(
            credentials_file=settings.FIREBASE_CREDENTIALS_FILE,
            timeout=settings.FCM_HTTP_TIMEOUT_SECONDS,
        )

    def _get_app(self) -> Any:
        if self._app is not None:
            return self._app
        import firebase_admin
        from firebase_admin import credentials

        with _lock:
            try:
                self._app = firebase_admin.get_app(_APP_NAME)
            except ValueError:
                cred = credentials.Certificate(self._credentials_file)
                self._app = firebase_admin.initialize_app(
                    cred, {"httpTimeout": self._timeout}, name=_APP_NAME
                )
        return self._app

    def send(self, token: str, message: Message) -> PushResult:
        try:
            from firebase_admin import exceptions as fb_exceptions
            from firebase_admin import messaging
        except ImportError:  # pragma: no cover - dependency is in requirements
            return PushResult(ok=False, error="firebase_admin_missing")

        if not self._credentials_file:
            return PushResult(ok=False, error="fcm_not_configured")

        try:
            app = self._get_app()
            messaging.send(
                messaging.Message(
                    token=token,
                    notification=messaging.Notification(title=message.title, body=message.body),
                    data=dict(message.data),
                    android=messaging.AndroidConfig(priority="high"),
                ),
                app=app,
            )
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as exc:
            return PushResult(ok=False, invalid_token=True, error=type(exc).__name__)
        except fb_exceptions.InvalidArgumentError as exc:
            # Malformed/unknown registration token.
            return PushResult(ok=False, invalid_token=True, error=type(exc).__name__)
        except (
            messaging.QuotaExceededError,
            fb_exceptions.UnavailableError,
            fb_exceptions.InternalError,
            fb_exceptions.DeadlineExceededError,
            fb_exceptions.UnknownError,
        ) as exc:
            return PushResult(ok=False, retryable=True, error=type(exc).__name__)
        except fb_exceptions.FirebaseError as exc:
            return PushResult(ok=False, error=type(exc).__name__)
        except Exception as exc:  # network errors, bad credentials file, ...
            logger.warning("FCM send failed: %s", type(exc).__name__)
            return PushResult(ok=False, retryable=True, error=type(exc).__name__)
        return PushResult(ok=True)
