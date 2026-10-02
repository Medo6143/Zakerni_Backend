from django.urls import path

from apps.core.api.views import AppMetaView, HealthCheckView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("meta/app", AppMetaView.as_view(), name="meta-app"),
]
