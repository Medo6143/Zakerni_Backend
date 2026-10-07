from __future__ import annotations

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import ERRORS_400, ErrorEnvelopeSerializer
from apps.core.api.throttling import LmsIngestDailyThrottle, LmsIngestThrottle, LmsSyncThrottle
from apps.moodle.api.ingest_serializers import (
    LmsIngestResultSerializer,
    LmsIngestSerializer,
    build_ingest_data,
)
from apps.moodle.api.serializers import (
    LmsConnectSerializer,
    LmsStatusSerializer,
    not_connected_payload,
)
from apps.moodle.selectors import moodle_account_for_user
from apps.moodle.services.connection import LmsConnectData, connect_lms, disconnect_lms
from apps.moodle.services.ingest import ingest_lms_data
from apps.moodle.services.lms import request_lms_sync


def _enqueue(account_id: uuid.UUID, countdown: int) -> None:
    from apps.moodle.tasks import sync_moodle_account_task

    sync_moodle_account_task.apply_async(args=[str(account_id)], countdown=countdown)


@extend_schema(tags=["me"])
class LmsStatusView(APIView):
    @extend_schema(
        summary="LMS connection and last sync status",
        description='Always 200: "connected": false and status "not_connected" when the '
        "student has not connected the university.",
        responses={200: LmsStatusSerializer},
    )
    def get(self, request: Request) -> Response:
        account = moodle_account_for_user(request.user.pk)
        if account is None:
            return Response(not_connected_payload())
        return Response(LmsStatusSerializer(account).data)

    @extend_schema(
        summary="Disconnect the university: remove Moodle items and the link",
        description="Deletes the Moodle link, soft-deletes Moodle-sourced items (their "
        "reminders are cancelled) and deactivates enrollments. Manual items, lectures and "
        "SIS data are kept.",
        responses={204: None},
    )
    def delete(self, request: Request) -> Response:
        from config import container

        disconnect_lms(request.user, scheduler=container.reminder_scheduler())
        return Response(status=204)


@extend_schema(tags=["me"])
class LmsConnectView(APIView):
    @extend_schema(
        summary="Connect the university LMS (no token or password is sent)",
        request=LmsConnectSerializer,
        responses={200: LmsStatusSerializer, 401: ErrorEnvelopeSerializer, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = LmsConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = connect_lms(request.user, LmsConnectData(**serializer.validated_data))
        return Response(LmsStatusSerializer(account).data)


@extend_schema(tags=["me"])
class LmsSyncView(APIView):
    throttle_classes = [LmsSyncThrottle]

    @extend_schema(
        summary="Trigger an LMS sync now (throttled to 1 per 5 minutes)",
        request=None,
        responses={
            202: LmsStatusSerializer,
            401: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        account = request_lms_sync(request.user, enqueue=_enqueue)
        return Response(LmsStatusSerializer(account).data, status=202)


@extend_schema(tags=["me"])
class LmsIngestView(APIView):
    throttle_classes = [LmsIngestThrottle, LmsIngestDailyThrottle]

    @extend_schema(
        summary="Store the Moodle data the phone fetched (device mode; throttled to "
        "1 per minute and 200 per day)",
        request=LmsIngestSerializer,
        responses={
            200: LmsIngestResultSerializer,
            401: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
            **ERRORS_400,
        },
    )
    def post(self, request: Request) -> Response:
        from config import container

        serializer = LmsIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = ingest_lms_data(
            request.user,
            build_ingest_data(serializer.validated_data),
            build_sync=container.sync_moodle_account_with,
        )
        return Response(LmsIngestResultSerializer(result).data)
