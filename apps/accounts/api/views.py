from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.api.serializers import (
    LoginResponseSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshSerializer,
    TokenPairSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from apps.accounts.api.throttling import LoginRateThrottle
from apps.accounts.services.auth import LoginWithLms
from apps.accounts.services.profile import delete_account, update_profile
from apps.core.api.serializers import ERRORS_400, ErrorEnvelopeSerializer
from apps.core.exceptions import ValidationAppError
from apps.moodle.integrations.http_client import HttpMoodleClient
from apps.notifications.services.devices import deactivate_device_token


def _login_service() -> LoginWithLms:
    client = HttpMoodleClient.from_settings()
    return LoginWithLms(auth_client=client, data_client=client)


@extend_schema(tags=["auth"])
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [LoginRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        summary="Log in with LMS credentials (the password is never stored)",
        request=LoginSerializer,
        responses={
            200: LoginResponseSerializer,
            401: ErrorEnvelopeSerializer,
            429: ErrorEnvelopeSerializer,
            503: ErrorEnvelopeSerializer,
            **ERRORS_400,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = _login_service()(
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )

        refresh = RefreshToken.for_user(result.user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(result.user).data,
                "is_new": result.is_new,
            },
            status=200,
        )


@extend_schema(tags=["auth"])
class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        summary="Rotate the refresh token",
        request=RefreshSerializer,
        responses={200: TokenPairSerializer, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            refresh = RefreshToken(serializer.validated_data["refresh"])
            access = str(refresh.access_token)
            new_refresh = str(refresh)
        except TokenError as exc:
            raise ValidationAppError(details={"refresh": [str(exc)]}) from exc
        return Response({"access": access, "refresh": new_refresh})


@extend_schema(tags=["auth"])
class LogoutView(APIView):
    @extend_schema(
        summary="Blacklist the refresh token and deactivate the device",
        request=LogoutSerializer,
        responses={204: None, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            pass

        fcm_token = serializer.validated_data.get("fcm_token")
        if fcm_token:
            deactivate_device_token(request.user, fcm_token)

        return Response(status=204)


@extend_schema(tags=["me"])
class MeView(APIView):
    @extend_schema(summary="Current user", responses=UserSerializer)
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)

    @extend_schema(
        summary="Update language / timezone",
        request=UserUpdateSerializer,
        responses={200: UserSerializer, **ERRORS_400},
    )
    def patch(self, request: Request) -> Response:
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = update_profile(request.user, **serializer.validated_data)
        return Response(UserSerializer(user).data)

    @extend_schema(
        summary="Delete the account and all personal data (reports are anonymised)",
        responses={204: None},
    )
    def delete(self, request: Request) -> Response:
        delete_account(request.user)
        return Response(status=204)
