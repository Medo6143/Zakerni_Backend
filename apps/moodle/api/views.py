from __future__ import annotations

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import ERRORS_400, ErrorEnvelopeSerializer
from apps.core.api.throttling import LmsIngestDailyThrottle, LmsIngestThrottle, LmsSyncThrottle
from apps.core.exceptions import NotFoundAppError
from apps.moodle.api.ingest_serializers import (
    LmsIngestResultSerializer,
    LmsIngestSerializer,
    build_ingest_data,
)
from apps.moodle.api.serializers import LmsStatusSerializer
from apps.moodle.selectors import moodle_account_for_user
from apps.moodle.services.ingest import ingest_lms_data
from apps.moodle.services.lms import request_lms_sync


def _enqueue(account_id: uuid.UUID, countdown: int) -> None:
    from apps.moodle.tasks import sync_moodle_account_task

    sync_moodle_account_task.apply_async(args=[str(account_id)], countdown=countdown)


@extend_schema(tags=["me"])
class LmsStatusView(APIView):
    @extend_schema(
        summary="LMS connection and last sync status",
        responses={200: LmsStatusSerializer, 404: ErrorEnvelopeSerializer},
    )
    def get(self, request: Request) -> Response:
        account = moodle_account_for_user(request.user.pk)
        if account is None:
            raise NotFoundAppError()
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
