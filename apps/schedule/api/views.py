from __future__ import annotations

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import ERRORS_400, ERRORS_400_404, ERRORS_404
from apps.schedule.api.presenters import course_detail_payload, item_payload, items_payload
from apps.schedule.api.serializers import (
    CourseDetailSerializer,
    CourseMuteSerializer,
    CourseSerializer,
    ItemCreateSerializer,
    ItemMuteSerializer,
    ItemRangeQuerySerializer,
    ItemSerializer,
    ItemUpdateSerializer,
    LectureScheduleSerializer,
    LectureScheduleWriteSerializer,
)
from apps.schedule.selectors import (
    enrollment_for_user,
    enrollments_for_user,
    item_for_user,
    items_in_range,
    lecture_schedule_for_user,
    lecture_schedules_for_user,
)
from apps.schedule.services import courses as course_services
from apps.schedule.services import items as item_services
from apps.schedule.services import lectures as lecture_services
from config import container


@extend_schema(tags=["items"])
class ItemListCreateView(APIView):
    @extend_schema(
        summary="Items in a date range (not paginated)",
        parameters=[ItemRangeQuerySerializer],
        responses={200: ItemSerializer(many=True), **ERRORS_400},
    )
    def get(self, request: Request) -> Response:
        query = ItemRangeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        items = items_in_range(
            request.user,
            data["from"],
            data["to"],
            item_type=data.get("type"),
            course_id=data.get("course"),
        )
        return Response(items_payload(request.user, items))

    @extend_schema(
        summary="Create a manual exam or quiz",
        request=ItemCreateSerializer,
        responses={201: ItemSerializer, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = ItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = item_services.create_manual_item(
            request.user, scheduler=container.reminder_scheduler(), **serializer.validated_data
        )
        return Response(item_payload(request.user, item.id), status=201)


@extend_schema(tags=["items"])
class ItemDetailView(APIView):
    @extend_schema(responses={200: ItemSerializer, **ERRORS_404})
    def get(self, request: Request, item_id: uuid.UUID) -> Response:
        return Response(item_payload(request.user, item_id))

    @extend_schema(
        summary="Update a manual exam or quiz",
        request=ItemUpdateSerializer,
        responses={200: ItemSerializer, **ERRORS_400_404},
    )
    def patch(self, request: Request, item_id: uuid.UUID) -> Response:
        item = item_for_user(request.user, item_id)
        serializer = ItemUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        item_services.update_manual_item(
            item, scheduler=container.reminder_scheduler(), **serializer.validated_data
        )
        return Response(item_payload(request.user, item_id))

    @extend_schema(summary="Delete a manual exam or quiz", responses={204: None, **ERRORS_400_404})
    def delete(self, request: Request, item_id: uuid.UUID) -> Response:
        item = item_for_user(request.user, item_id)
        item_services.delete_manual_item(item, scheduler=container.reminder_scheduler())
        return Response(status=204)


@extend_schema(tags=["items"])
class ItemMuteView(APIView):
    @extend_schema(
        summary="Mute or unmute one item",
        request=ItemMuteSerializer,
        responses={200: ItemSerializer, **ERRORS_400_404},
    )
    def patch(self, request: Request, item_id: uuid.UUID) -> Response:
        item = item_for_user(request.user, item_id)
        serializer = ItemMuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item_services.set_item_muted(
            item,
            is_muted=serializer.validated_data["is_muted"],
            scheduler=container.reminder_scheduler(),
        )
        return Response(item_payload(request.user, item_id))


@extend_schema(tags=["lectures"])
class LectureListCreateView(APIView):
    @extend_schema(responses=LectureScheduleSerializer(many=True))
    def get(self, request: Request) -> Response:
        schedules = lecture_schedules_for_user(request.user)
        return Response(LectureScheduleSerializer(schedules, many=True).data)

    @extend_schema(
        summary="Create a weekly lecture (occurrences are generated immediately)",
        request=LectureScheduleWriteSerializer,
        responses={201: LectureScheduleSerializer, **ERRORS_400},
    )
    def post(self, request: Request) -> Response:
        serializer = LectureScheduleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = lecture_services.create_lecture_schedule(
            request.user, scheduler=container.reminder_scheduler(), **serializer.validated_data
        )
        return Response(LectureScheduleSerializer(schedule).data, status=201)


@extend_schema(tags=["lectures"])
class LectureDetailView(APIView):
    @extend_schema(
        summary="Update a lecture schedule (future occurrences are regenerated)",
        request=LectureScheduleWriteSerializer,
        responses={200: LectureScheduleSerializer, **ERRORS_400_404},
    )
    def patch(self, request: Request, schedule_id: uuid.UUID) -> Response:
        schedule = lecture_schedule_for_user(request.user, schedule_id)
        serializer = LectureScheduleWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        schedule = lecture_services.update_lecture_schedule(
            schedule, scheduler=container.reminder_scheduler(), **serializer.validated_data
        )
        return Response(LectureScheduleSerializer(schedule).data)

    @extend_schema(
        summary="Delete a lecture schedule (future occurrences are removed)",
        responses={204: None, **ERRORS_404},
    )
    def delete(self, request: Request, schedule_id: uuid.UUID) -> Response:
        schedule = lecture_schedule_for_user(request.user, schedule_id)
        lecture_services.delete_lecture_schedule(schedule)
        return Response(status=204)


@extend_schema(tags=["courses"])
class CourseListView(APIView):
    @extend_schema(responses=CourseSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(CourseSerializer(enrollments_for_user(request.user), many=True).data)


@extend_schema(tags=["courses"])
class CourseDetailView(APIView):
    @extend_schema(
        summary="Course detail: tutor, group, next 30 days of items and lecture times",
        responses={200: CourseDetailSerializer, **ERRORS_404},
    )
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        return Response(course_detail_payload(request.user, course_id))

    @extend_schema(
        summary="Mute or unmute a course",
        request=CourseMuteSerializer,
        responses={200: CourseSerializer, **ERRORS_400_404},
    )
    def patch(self, request: Request, course_id: uuid.UUID) -> Response:
        enrollment = enrollment_for_user(request.user, course_id)
        serializer = CourseMuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course_services.set_course_muted(
            enrollment,
            is_muted=serializer.validated_data["is_muted"],
            scheduler=container.reminder_scheduler(),
        )
        return Response(CourseSerializer(enrollment_for_user(request.user, course_id)).data)
