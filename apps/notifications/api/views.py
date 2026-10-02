from __future__ import annotations

import hmac
import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.pagination import CursorSetPagination
from apps.core.api.serializers import ERRORS_400, ErrorEnvelopeSerializer
from apps.core.exceptions import ApplicationError
from apps.notifications.api.serializers import (
    DeviceRegisterSerializer,
    DeviceSerializer,
    MarkReadSerializer,
    NotificationSerializer,
    PaginatedNotificationSerializer,
    TelegramLinkSerializer,
    TelegramStatusSerializer,
    TelegramUpdateSerializer,
    UnreadCountSerializer,
)
from apps.notifications.selectors import (
    notifications_for_user,
    telegram_link_for_user,
    unread_notifications_count,
)
from apps.notifications.services import devices as device_services
from apps.notifications.services import telegram_linking
from apps.notifications.services.history import mark_notifications_read
from config import container

logger = logging.getLogger(__name__)


class WebhookForbidden(ApplicationError):
    code = "forbidden"
    status = 403


@extend_schema(tags=["devices"])
class DeviceRegisterView(APIView):
    @extend_schema(
        summary="Register or refresh an FCM token (upsert)",
        request=DeviceRegisterSerializer,
        responses={200: DeviceSerializer, 201: DeviceSerializer, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        registration = device_services.register_device(
            request.user, scheduler=container.reminder_scheduler(), **serializer.validated_data
        )
        return Response(
            DeviceSerializer(registration.device).data,
            status=201 if registration.created else 200,
        )


@extend_schema(tags=["devices"])
class DeviceDetailView(APIView):
    @extend_schema(summary="Deactivate an FCM token", responses={204: None})
    def delete(self, request: Request, fcm_token: str) -> Response:
        device_services.deactivate_device_token(request.user, fcm_token)
        return Response(status=204)


def _telegram_status(user) -> dict:  # type: ignore[no-untyped-def]
    link = telegram_link_for_user(user)
    return {
        "linked": link is not None,
        "username": link.username if link else None,
        "linked_at": link.linked_at if link else None,
    }


@extend_schema(tags=["telegram"])
class TelegramStatusView(APIView):
    @extend_schema(summary="Telegram link status", responses=TelegramStatusSerializer)
    def get(self, request: Request) -> Response:
        return Response(TelegramStatusSerializer(_telegram_status(request.user)).data)

    @extend_schema(summary="Unlink Telegram", responses={204: None})
    def delete(self, request: Request) -> Response:
        telegram_linking.unlink_telegram(request.user)
        return Response(status=204)


@extend_schema(tags=["telegram"])
class TelegramLinkView(APIView):
    @extend_schema(
        summary="Create a one-time deep link (10 min TTL)",
        request=None,
        responses=TelegramLinkSerializer,
    )
    def post(self, request: Request) -> Response:
        invitation = telegram_linking.create_link_token(request.user)
        return Response(
            TelegramLinkSerializer(
                {"url": invitation.url, "expires_at": invitation.expires_at}
            ).data
        )


@extend_schema(tags=["telegram"])
class TelegramWebhookView(APIView):
    """Called by Telegram. Protected by ``X-Telegram-Bot-Api-Secret-Token``."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    @extend_schema(
        summary="Telegram bot webhook (public, secret header)",
        request=TelegramUpdateSerializer,
        responses={200: None, 403: ErrorEnvelopeSerializer},
    )
    def post(self, request: Request) -> Response:
        expected = settings.TELEGRAM_WEBHOOK_SECRET
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
            raise WebhookForbidden()
        update = request.data if isinstance(request.data, dict) else {}
        try:
            telegram_linking.handle_telegram_update(
                update,
                bot=container.telegram_bot_client(),
                scheduler=container.reminder_scheduler(),
            )
        except Exception:  # never make Telegram retry an update forever
            logger.exception("Telegram webhook update failed")
        return Response(status=200)


class NotificationPagination(CursorSetPagination):
    page_size = 20


@extend_schema(tags=["notifications"])
class NotificationListView(APIView):
    pagination_class = NotificationPagination

    @extend_schema(
        summary="Notification history, newest first (cursor paginated, 20 per page)",
        parameters=[
            OpenApiParameter("cursor", str, OpenApiParameter.QUERY, required=False),
        ],
        responses=PaginatedNotificationSerializer,
    )
    def get(self, request: Request) -> Response:
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(notifications_for_user(request.user), request, view=self)
        return paginator.get_paginated_response(NotificationSerializer(page, many=True).data)


@extend_schema(tags=["notifications"])
class UnreadCountView(APIView):
    @extend_schema(summary="Unread notifications count", responses=UnreadCountSerializer)
    def get(self, request: Request) -> Response:
        return Response({"count": unread_notifications_count(request.user)})


@extend_schema(tags=["notifications"])
class MarkReadView(APIView):
    @extend_schema(
        summary="Mark notifications as read (empty ids = all)",
        request=MarkReadSerializer,
        responses={204: None, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mark_notifications_read(request.user, serializer.validated_data.get("ids") or None)
        return Response(status=204)
