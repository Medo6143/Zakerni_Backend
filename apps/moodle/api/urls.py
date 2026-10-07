from django.urls import path

from apps.moodle.api.views import LmsIngestView, LmsStatusView, LmsSyncView

urlpatterns = [
    path("me/lms", LmsStatusView.as_view(), name="me-lms"),
    path("me/lms/ingest", LmsIngestView.as_view(), name="me-lms-ingest"),
    path("me/lms/sync", LmsSyncView.as_view(), name="me-lms-sync"),
]
