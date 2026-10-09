from django.urls import path

from apps.moodle.api.views import (
    AnnouncementListView,
    LmsConnectView,
    LmsIngestView,
    LmsStatusView,
    LmsSyncView,
)

urlpatterns = [
    path("announcements", AnnouncementListView.as_view(), name="announcements"),
    path("me/lms", LmsStatusView.as_view(), name="me-lms"),
    path("me/lms/connect", LmsConnectView.as_view(), name="me-lms-connect"),
    path("me/lms/ingest", LmsIngestView.as_view(), name="me-lms-ingest"),
    path("me/lms/sync", LmsSyncView.as_view(), name="me-lms-sync"),
]
