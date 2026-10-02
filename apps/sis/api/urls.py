from django.urls import path

from apps.sis.api.views import SisAccountView, SisSyncView

urlpatterns = [
    path("me/sis", SisAccountView.as_view(), name="me-sis"),
    path("me/sis/sync", SisSyncView.as_view(), name="me-sis-sync"),
]
