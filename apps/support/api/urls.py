from django.urls import path

from apps.support.api.views import (
    ReportCategoriesView,
    ReportDetailView,
    ReportListCreateView,
    ReportReplyCreateView,
)

urlpatterns = [
    path("reports", ReportListCreateView.as_view(), name="reports"),
    path("reports/categories", ReportCategoriesView.as_view(), name="report-categories"),
    path("reports/<uuid:report_id>", ReportDetailView.as_view(), name="report-detail"),
    path(
        "reports/<uuid:report_id>/replies",
        ReportReplyCreateView.as_view(),
        name="report-replies",
    ),
]
