from __future__ import annotations

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import ERRORS_400, ErrorEnvelopeSerializer
from apps.core.api.throttling import SisIngestDailyThrottle, SisIngestThrottle, SisSyncThrottle
from apps.sis.api.ingest_serializers import (
    SisIngestResultSerializer,
    SisIngestSerializer,
    build_sis_entries,
)
from apps.sis.api.serializers import SisConnectSerializer, SisStatusSerializer, sis_status_data
from apps.sis.selectors import sis_account_for_user
from apps.sis.services.account import (
    connect_sis_account,
    disconnect_sis_account,
    request_sis_sync,
)
from apps.sis.services.ingest import ingest_sis_entries


def _enqueue(account_id: uuid.UUID, countdown: int) -> None:
    from apps.sis.tasks import sync_sis_account_task

    sync_sis_account_task.apply_async(args=[str(account_id)], countdown=countdown)


@extend_schema(tags=["sis"])
class SisAccountView(APIView):
    @extend_schema(
        summary="SIS connection and last sync status (never the password)",
        responses={200: SisStatusSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(sis_status_data(sis_account_for_user(request.user.pk)))

    @extend_schema(
        summary="Connect the SIS: signs in once to verify, then stores the password "
        "encrypted and starts a sync",
        request=SisConnectSerializer,
        responses={
            201: SisStatusSerializer,
            400: ErrorEnvelopeSerializer,
            503: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        from config import container

        serializer = SisConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = connect_sis_account(
            request.user,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
            client=container.sis_client(),
            enqueue=_enqueue,
        )
        return Response(sis_status_data(sis_account_for_user(account.user_id)), status=201)

    @extend_schema(
        summary="Disconnect the SIS: deletes the stored password and the imported "
        "future exams and timetables",
        responses={204: None, 404: ErrorEnvelopeSerializer},
    )
    def delete(self, request: Request) -> Response:
        from config import container

        disconnect_sis_account(request.user, scheduler=container.reminder_scheduler())
        return Response(status=204)


@extend_schema(tags=["sis"])
class SisSyncView(APIView):
    throttle_classes = [SisSyncThrottle]

    @extend_schema(
        summary="Trigger an SIS sync now (throttled to 1 per 5 minutes)",
        request=None,
        responses={
            202: SisStatusSerializer,
            400: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        account = request_sis_sync(request.user, enqueue=_enqueue)
        return Response(sis_status_data(sis_account_for_user(account.user_id)), status=202)


@extend_schema(tags=["sis"])
class SisIngestView(APIView):
    throttle_classes = [SisIngestThrottle, SisIngestDailyThrottle]

    @extend_schema(
        summary="Store the SIS schedule the phone fetched (device mode; 404 unless "
        "SIS_INGEST_ENABLED; throttled to 1 per minute and 50 per day)",
        request=SisIngestSerializer,
        responses={
            200: SisIngestResultSerializer,
            401: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
            **ERRORS_400,
        },
    )
    def post(self, request: Request) -> Response:
        from config import container

        serializer = SisIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = ingest_sis_entries(
            request.user,
            build_sis_entries(serializer.validated_data),
            build_sync=container.sync_sis_account_with,
        )
        return Response(SisIngestResultSerializer(result).data)
