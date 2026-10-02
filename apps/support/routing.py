from django.urls import path

from apps.support.consumers import ReportChatConsumer

websocket_urlpatterns = [
    path("ws/v1/reports/<uuid:report_id>/", ReportChatConsumer.as_asgi()),
]
