"""Direct message: a broadcast whose audience is exactly one user."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.broadcasts.models import Broadcast
from apps.broadcasts.services.send import start_broadcast
from apps.core.exceptions import ApplicationError


class EmptyDirectMessage(ApplicationError):
    code = "empty_direct_message"
    status = 400
    message = _("Write a title and a message in at least one language.")


def create_direct_broadcast(
    *,
    sender: User,
    recipient: User,
    title_ar: str = "",
    body_ar: str = "",
    title_en: str = "",
    body_en: str = "",
    send_push: bool = True,
    send_telegram: bool = True,
    enqueue: Callable[[Any], None],
) -> Broadcast:
    """Create the broadcast for ``recipient`` and start sending it.

    Both language columns are required by the model, so a message written in one
    language is used for both: the user always receives text.
    """
    title_ar, body_ar = title_ar.strip(), body_ar.strip()
    title_en, body_en = title_en.strip(), body_en.strip()
    has_ar = bool(title_ar and body_ar)
    has_en = bool(title_en and body_en)
    if not (has_ar or has_en):
        raise EmptyDirectMessage()
    if not has_ar:
        title_ar, body_ar = title_en, body_en
    if not has_en:
        title_en, body_en = title_ar, body_ar
    broadcast = Broadcast.objects.create(
        created_by=sender,
        recipient=recipient,
        title_ar=title_ar,
        body_ar=body_ar,
        title_en=title_en,
        body_en=body_en,
        send_push=send_push,
        send_telegram=send_telegram,
    )
    return start_broadcast(broadcast, enqueue=enqueue)
