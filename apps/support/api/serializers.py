from __future__ import annotations

import json
from typing import Any

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.support.models import Report, ReportReply


class ReportCategorySerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]  # shadows Field.label


@extend_schema_field({"type": "object", "additionalProperties": True})
class DeviceInfoField(serializers.Field):
    """Accepts a JSON object, or a JSON string (multipart form field)."""

    default_error_messages = {"invalid": _("Must be a JSON object.")}

    def to_internal_value(self, data: Any) -> dict:
        if isinstance(data, str):
            try:
                data = json.loads(data) if data.strip() else {}
            except ValueError:
                self.fail("invalid")
        if not isinstance(data, dict):
            self.fail("invalid")
        if len(json.dumps(data)) > 5000:
            self.fail("invalid")
        return data

    def to_representation(self, value: Any) -> Any:
        return value


class ReportCreateSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=Report.Category.choices)
    description = serializers.CharField(max_length=5000)
    device_info = DeviceInfoField(required=False)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True)
    attachments = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        help_text="Up to 3 images (JPEG, PNG or WEBP), 5 MB each. `attachments[]` is also accepted.",
    )


class ReportReplySerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportReply
        fields = ("id", "body", "is_staff", "created_at")
        read_only_fields = fields


class ReportReplyCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000)


class ReportSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    attachments = serializers.SerializerMethodField()
    replies = ReportReplySerializer(many=True, read_only=True)

    class Meta:
        model = Report
        fields = (
            "id",
            "category",
            "category_label",
            "description",
            "status",
            "status_label",
            "attachments",
            "replies",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.URLField()))
    def get_attachments(self, obj: Report) -> list[str]:
        request = self.context.get("request")
        urls = []
        for attachment in obj.attachments.all():
            url = attachment.file.url
            urls.append(request.build_absolute_uri(url) if request is not None else url)
        return urls
