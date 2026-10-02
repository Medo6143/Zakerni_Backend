"""Push channel: delivers to every active FCM device of the user."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from apps.notifications.models import Channel
from apps.notifications.protocols import DeliveryResult, Message, PushSender
from apps.notifications.selectors import active_devices_for_user, user_has_active_device
from apps.notifications.services.devices import deactivate_device

if TYPE_CHECKING:
    from apps.accounts.models import User


class FcmChannel:
    code: ClassVar[str] = Channel.PUSH.value

    def __init__(self, sender: PushSender) -> None:
        self._sender = sender

    def is_available_for(self, user: User) -> bool:
        return user_has_active_device(user)

    def send(self, user: User, message: Message) -> DeliveryResult:
        devices = list(active_devices_for_user(user))
        if not devices:
            return DeliveryResult.failure("no_active_device")

        delivered = 0
        retryable = False
        errors: list[str] = []
        for device in devices:
            result = self._sender.send(device.fcm_token, message)
            if result.ok:
                delivered += 1
                continue
            errors.append(result.error)
            if result.invalid_token:
                # Invalid/unregistered token -> Device.is_active = False (docs/01 section 5).
                deactivate_device(device)
            elif result.retryable:
                retryable = True

        if delivered:
            return DeliveryResult.success()
        return DeliveryResult.failure(
            ", ".join(e for e in errors if e) or "push_failed", retryable=retryable
        )
