"""Shared serializers (error envelope for the OpenAPI schema, meta)."""

from __future__ import annotations

from rest_framework import serializers


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField(child=serializers.JSONField())


class ErrorEnvelopeSerializer(serializers.Serializer):
    """``{"error": {"code", "message", "details"}}`` for every non-2xx response."""

    error = ErrorBodySerializer()


class AppMetaSerializer(serializers.Serializer):
    min_supported_version = serializers.CharField()
    latest_version = serializers.CharField()
    privacy_url = serializers.CharField(allow_blank=True)
    support_telegram = serializers.CharField(allow_blank=True)
    developer_name = serializers.CharField(allow_blank=True)


ERRORS_400 = {400: ErrorEnvelopeSerializer}
ERRORS_404 = {404: ErrorEnvelopeSerializer}
ERRORS_400_404 = {400: ErrorEnvelopeSerializer, 404: ErrorEnvelopeSerializer}
