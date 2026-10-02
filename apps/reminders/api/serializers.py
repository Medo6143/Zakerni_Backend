from rest_framework import serializers

from apps.reminders.defaults import MAX_OFFSETS, OFFSET_MAX_MINUTES, OFFSET_MIN_MINUTES
from apps.reminders.models import ReminderRule


def _offsets_field() -> serializers.ListField:
    return serializers.ListField(
        child=serializers.IntegerField(min_value=OFFSET_MIN_MINUTES, max_value=OFFSET_MAX_MINUTES),
        min_length=1,
        max_length=MAX_OFFSETS,
        help_text="Minutes before the item; 1..5 unique values, each 5..20160.",
    )


class ReminderRuleSerializer(serializers.ModelSerializer):
    offsets_minutes = serializers.ListField(child=serializers.IntegerField())

    class Meta:
        model = ReminderRule
        fields = ("item_type", "offsets_minutes", "push_enabled", "telegram_enabled")
        read_only_fields = fields


class ReminderRuleUpdateSerializer(serializers.Serializer):
    offsets_minutes = _offsets_field()
    push_enabled = serializers.BooleanField()
    telegram_enabled = serializers.BooleanField()


class ItemReminderOverrideSerializer(serializers.Serializer):
    offsets_minutes = _offsets_field()
