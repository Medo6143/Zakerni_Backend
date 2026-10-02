from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import AppMetaSerializer


@extend_schema(tags=["meta"])
class HealthCheckView(APIView):
    """Unauthenticated smoke-test endpoint used by Phase 0 tooling and infra checks."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        responses=inline_serializer("HealthStatus", fields={"status": serializers.CharField()})
    )
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


@extend_schema(tags=["meta"])
class AppMetaView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses=AppMetaSerializer, summary="App version and links")
    def get(self, request: Request) -> Response:
        return Response(
            AppMetaSerializer(
                {
                    "min_supported_version": settings.APP_MIN_SUPPORTED_VERSION,
                    "latest_version": settings.APP_LATEST_VERSION,
                    "privacy_url": settings.APP_PRIVACY_URL,
                    "support_telegram": settings.APP_SUPPORT_TELEGRAM,
                }
            ).data
        )
