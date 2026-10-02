"""Aggregate router for all /api/v1/ endpoints."""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.api.urls")),
    path("", include("apps.accounts.api.urls")),
    path("", include("apps.moodle.api.urls")),
    path("", include("apps.sis.api.urls")),
    path("", include("apps.schedule.api.urls")),
    path("", include("apps.reminders.api.urls")),
    path("", include("apps.notifications.api.urls")),
    path("", include("apps.support.api.urls")),
]
