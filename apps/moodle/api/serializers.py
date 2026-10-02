from rest_framework import serializers

from apps.moodle.models import MoodleAccount


class LmsStatusSerializer(serializers.ModelSerializer):
    """Never includes the token (hard rule #2)."""

    class Meta:
        model = MoodleAccount
        fields = ("status", "last_synced_at", "last_sync_error")
        read_only_fields = fields
