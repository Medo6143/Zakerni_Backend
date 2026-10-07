from rest_framework import serializers

from apps.core.api.ingest_fields import SafeCharField
from apps.moodle.models import MoodleAccount

NOT_CONNECTED = "not_connected"


class LmsStatusSerializer(serializers.ModelSerializer):
    """Never includes the token (hard rule #2)."""

    connected = serializers.SerializerMethodField()
    status = serializers.ChoiceField(
        choices=[*MoodleAccount.Status.choices, (NOT_CONNECTED, "Not connected")]
    )

    class Meta:
        model = MoodleAccount
        fields = ("connected", "status", "last_synced_at", "last_sync_error")
        read_only_fields = fields

    def get_connected(self, obj: MoodleAccount) -> bool:
        return True


def not_connected_payload() -> dict:
    return {
        "connected": False,
        "status": NOT_CONNECTED,
        "last_synced_at": None,
        "last_sync_error": "",
    }


class LmsConnectSerializer(serializers.Serializer):
    username = SafeCharField(max_length=150)
    moodle_user_id = serializers.IntegerField(min_value=1, max_value=2**31 - 1)
    full_name = SafeCharField(max_length=255, allow_blank=True, default="")
    email = serializers.EmailField(max_length=254, allow_blank=True, default="")
    site_url = serializers.URLField(max_length=200)
