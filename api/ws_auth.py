"""
JWT auth middleware for Channels WebSocket connections.

Browsers can't attach Authorization headers to a WebSocket handshake, so we
expect the access token in the query string: ws://.../ws/chat/<id>/?token=<jwt>.
The middleware validates it and attaches the User to scope['user']. If the
token is missing or invalid, scope['user'] is AnonymousUser and the consumer
should close the connection.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user_from_token(raw_token):
    # Import inside the function so Django app registry is ready by the time
    # this middleware actually runs (asgi.py initializes Django first).
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
    from django.contrib.auth import get_user_model

    try:
        token = AccessToken(raw_token)
        user_id = token['user_id']
    except (TokenError, InvalidToken, KeyError):
        return AnonymousUser()

    User = get_user_model()
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        params = parse_qs(query_string)
        raw_token = params.get('token', [None])[0]

        if raw_token:
            scope['user'] = await _get_user_from_token(raw_token)
        else:
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)
