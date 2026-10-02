"""Daily cleanup (docs/01 section 3): expired Telegram link tokens."""

from __future__ import annotations

from apps.notifications.selectors import expired_link_tokens


def delete_expired_link_tokens() -> int:
    deleted, _unused = expired_link_tokens().delete()
    return deleted
