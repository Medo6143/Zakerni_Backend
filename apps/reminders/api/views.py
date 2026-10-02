from __future__ import annotations

import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import ERRORS_400_404, ErrorEnvelopeSerializer
from apps.reminders.api.serializers import (
    ItemReminderOverrideSerializer,
    ReminderRuleSerializer,
    ReminderRuleUpdateSerializer,
)
from apps.reminders.selectors import reminder_rules_for_user
from apps.reminders.services import rules as rule_services
from apps.schedule.api.presenters import item_payload
from apps.schedule.api.serializers import ItemSerializer
from apps.schedule.models import ItemType
from apps.schedule.selectors import item_for_user
from config import container


@extend_schema(tags=["reminders"])
class ReminderRuleListView(APIView):
    @extend_schema(
        summary="Reminder rules (always one per item type)",
        responses=ReminderRuleSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        rule_services.ensure_reminder_rules(request.user)
        return Response(
            ReminderRuleSerializer(reminder_rules_for_user(request.user), many=True).data
        )


@extend_schema(tags=["reminders"])
class ReminderRuleDetailView(APIView):
    @extend_schema(
        summary="Replace the rule of one item type (reschedules future reminders)",
        parameters=[
            OpenApiParameter(
                "item_type", str, OpenApiParameter.PATH, enum=[t.value for t in ItemType]
            )
        ],
        request=ReminderRuleUpdateSerializer,
        responses={200: ReminderRuleSerializer, **ERRORS_400_404},
    )
    def put(self, request: Request, item_type: str) -> Response:
        serializer = ReminderRuleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = rule_services.update_reminder_rule(
            request.user,
            item_type,
            scheduler=container.reminder_scheduler(),
            **serializer.validated_data,
        )
        return Response(ReminderRuleSerializer(rule).data)


@extend_schema(tags=["reminders"])
class ConfirmDefaultsView(APIView):
    @extend_schema(
        summary="Onboarding: confirm the default reminders", request=None, responses={204: None}
    )
    def post(self, request: Request) -> Response:
        rule_services.confirm_default_rules(request.user)
        return Response(status=204)


@extend_schema(tags=["reminders"])
class ItemReminderOverrideView(APIView):
    @extend_schema(
        summary="Custom reminder times for one item",
        request=ItemReminderOverrideSerializer,
        responses={200: ItemSerializer, **ERRORS_400_404},
    )
    def put(self, request: Request, item_id: uuid.UUID) -> Response:
        item = item_for_user(request.user, item_id)
        serializer = ItemReminderOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule_services.set_item_override(
            item,
            serializer.validated_data["offsets_minutes"],
            scheduler=container.reminder_scheduler(),
        )
        return Response(item_payload(request.user, item_id))

    @extend_schema(
        summary="Back to the type rule",
        responses={204: None, 404: ErrorEnvelopeSerializer},
    )
    def delete(self, request: Request, item_id: uuid.UUID) -> Response:
        item = item_for_user(request.user, item_id)
        rule_services.clear_item_override(item, scheduler=container.reminder_scheduler())
        return Response(status=204)
