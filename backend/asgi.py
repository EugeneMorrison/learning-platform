"""
ASGI config for backend project.

Routes HTTP traffic to Django's regular ASGI application, and WebSocket
traffic through the JWT auth middleware into Channels URL routing.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# Initialize Django ASGI app FIRST, before importing anything that touches
# the ORM. Channels and any code that imports models must come after this.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from api.routing import websocket_urlpatterns  # noqa: E402
from api.ws_auth import JWTAuthMiddleware  # noqa: E402


application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': JWTAuthMiddleware(
        URLRouter(websocket_urlpatterns)
    ),
})
