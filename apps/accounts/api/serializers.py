from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import User
from apps.notifications.selectors import is_telegram_linked


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
    fcm_token = serializers.CharField(required=False, allow_blank=True)


class OnboardingSerializer(serializers.Serializer):
    defaults_confirmed = serializers.BooleanField()


class UserSerializer(serializers.ModelSerializer):
    telegram_linked = serializers.SerializerMethodField()
    onboarding = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "full_name",
            "moodle_username",
            "email",
            "language",
            "timezone",
            "telegram_linked",
            "onboarding",
        )
        read_only_fields = ("id", "moodle_username", "email", "telegram_linked", "onboarding")

    def get_telegram_linked(self, obj: User) -> bool:
        # Read through the selector (not the cached reverse relation, which can be
        # stale on the request user right after linking/unlinking).
        return is_telegram_linked(obj)

    @extend_schema_field(OnboardingSerializer)
    def get_onboarding(self, obj: User) -> dict:
        return {"defaults_confirmed": obj.reminder_defaults_confirmed_at is not None}


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()
    is_new = serializers.BooleanField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("language", "timezone")

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise serializers.ValidationError(_("Unknown timezone.")) from exc
        return value
