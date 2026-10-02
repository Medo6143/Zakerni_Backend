from __future__ import annotations

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import (
    ERRORS_400,
    ERRORS_400_404,
    ERRORS_404,
    ErrorEnvelopeSerializer,
)
from apps.core.api.throttling import ReportCreateThrottle
from apps.support.api.serializers import (
    ReportCategorySerializer,
    ReportCreateSerializer,
    ReportReplyCreateSerializer,
    ReportReplySerializer,
    ReportSerializer,
)
from apps.support.models import Report
from apps.support.selectors import report_for_user, reports_for_user
from apps.support.services import reports as report_services
from config import container


@extend_schema(tags=["reports"])
class ReportCategoriesView(APIView):
    @extend_schema(
        summary="Report categories (translated)", responses=ReportCategorySerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        data = [{"code": code, "label": str(label)} for code, label in Report.Category.choices]
        return Response(ReportCategorySerializer(data, many=True).data)


@extend_schema(tags=["reports"])
class ReportListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_throttles(self):  # type: ignore[no-untyped-def]
        # 10 reports per day per user; reading the list is not throttled.
        return [ReportCreateThrottle()] if self.request.method == "POST" else []

    @extend_schema(summary="My reports", responses=ReportSerializer(many=True))
    def get(self, request: Request) -> Response:
        reports = reports_for_user(request.user)
        return Response(ReportSerializer(reports, many=True, context={"request": request}).data)

    @extend_schema(
        summary="Report a problem (multipart, up to 3 images of 5 MB)",
        request={"multipart/form-data": ReportCreateSerializer},
        responses={201: ReportSerializer, 429: ErrorEnvelopeSerializer, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        files = list(request.FILES.getlist("attachments")) + list(
            request.FILES.getlist("attachments[]")
        )
        data.pop("attachments", None)
        report = report_services.create_report(request.user, attachments=files, **data)
        return Response(
            ReportSerializer(
                report_for_user(request.user, report.id), context={"request": request}
            ).data,
            status=201,
        )


@extend_schema(tags=["reports"])
class ReportDetailView(APIView):
    @extend_schema(summary="Report with replies", responses={200: ReportSerializer, **ERRORS_404})
    def get(self, request: Request, report_id: uuid.UUID) -> Response:
        report = report_for_user(request.user, report_id)
        return Response(ReportSerializer(report, context={"request": request}).data)


@extend_schema(tags=["reports"])
class ReportReplyCreateView(APIView):
    @extend_schema(
        summary="Add a follow-up to my report",
        request=ReportReplyCreateSerializer,
        responses={201: ReportReplySerializer, **ERRORS_400_404},
    )
    def post(self, request: Request, report_id: uuid.UUID) -> Response:
        report = report_for_user(request.user, report_id)
        serializer = ReportReplyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply = report_services.add_user_reply(
            report,
            request.user,
            serializer.validated_data["body"],
            broadcaster=container.reply_broadcaster(),
        )
        return Response(ReportReplySerializer(reply).data, status=201)
