"""ASGI entry point: HTTP (Django) + WebSocket (Channels).

Served by ``daphne`` (``runserver`` in development, ``daphne config.asgi:application``
or ``uvicorn config.asgi:application`` in production).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# Initialise Django before importing anything that touches models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.core.ws_auth import WebSocketAuthStack  # noqa: E402
from apps.support.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": WebSocketAuthStack(URLRouter(websocket_urlpatterns)),
    }
)
