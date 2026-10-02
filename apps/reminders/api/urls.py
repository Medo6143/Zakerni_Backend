from django.urls import path

from apps.reminders.api.views import (
    ConfirmDefaultsView,
    ItemReminderOverrideView,
    ReminderRuleDetailView,
    ReminderRuleListView,
)

urlpatterns = [
    path("reminder-rules", ReminderRuleListView.as_view(), name="reminder-rules"),
    # Declared before the <item_type> route so it is not captured as a type.
    path(
        "reminder-rules/confirm-defaults",
        ConfirmDefaultsView.as_view(),
        name="reminder-rules-confirm-defaults",
    ),
    path("reminder-rules/<str:item_type>", ReminderRuleDetailView.as_view(), name="reminder-rule"),
    path(
        "items/<uuid:item_id>/reminders",
        ItemReminderOverrideView.as_view(),
        name="item-reminders",
    ),
]
