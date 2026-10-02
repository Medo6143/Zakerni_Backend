from rest_framework import serializers

from apps.notifications.models import Device, Notification


class DeviceRegisterSerializer(serializers.Serializer):
    fcm_token = serializers.CharField(max_length=4096)
    platform = serializers.ChoiceField(choices=Device.Platform.choices)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    os_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    model = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = (
            "id",
            "platform",
            "app_version",
            "os_version",
            "model",
            "is_active",
            "last_seen_at",
        )
        read_only_fields = fields


class TelegramStatusSerializer(serializers.Serializer):
    linked = serializers.BooleanField()
    username = serializers.CharField(allow_blank=True, allow_null=True)
    linked_at = serializers.DateTimeField(allow_null=True)


class TelegramLinkSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_at = serializers.DateTimeField()


class TelegramUpdateSerializer(serializers.Serializer):
    """Documentation only: a Telegram ``Update`` object (only ``message`` is used)."""

    update_id = serializers.IntegerField()
    message = serializers.DictField(required=False)


class NotificationSerializer(serializers.ModelSerializer):
    item_id = serializers.UUIDField(allow_null=True, read_only=True)
    report_id = serializers.UUIDField(allow_null=True, read_only=True)

    class Meta:
        model = Notification
        fields = ("id", "kind", "title", "body", "item_id", "report_id", "read_at", "created_at")
        read_only_fields = fields


class PaginatedNotificationSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = NotificationSerializer(many=True)


class UnreadCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        help_text="Notification ids to mark as read; empty or omitted = all.",
    )
