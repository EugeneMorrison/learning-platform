"""
WebSocket consumer for course chat.

Conversation model: a chat exists between two users (e.g. teacher ↔ student)
within a single course. Both sides connect with the SAME (course_id, other_user_id)
pair but each from their own perspective. We derive a stable group name from
the sorted user-id pair so both sockets end up in the same group regardless
of who initiated.

URL: ws/chat/<course_id>/<other_user_id>/?token=<jwt>

Close codes: 4001 not logged in (missing / expired token: the client
refreshes its token and reconnects), 4003 not allowed (outsider, wrong pair,
unknown or malformed course id: the client does not retry).

Server → client frames: a saved message (MessageSerializer data), or, to the
sender only, {"error": "too_long", "max_length": N} for a rejected message.
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .chat import MAX_MESSAGE_LENGTH, chat_allowed, chat_group, new_message_event, user_group


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self._refuse(4001)
            return

        self.course_id = self.scope['url_route']['kwargs']['course_id']
        self.other_user_id = int(self.scope['url_route']['kwargs']['other_user_id'])
        self.user_id = user.id

        # Verify this user is allowed to chat in this course with this other user.
        allowed = await self._verify_participants(
            self.course_id, self.user_id, self.other_user_id
        )
        if not allowed:
            await self._refuse(4003)
            return

        self.group_name = chat_group(self.course_id, self.user_id, self.other_user_id)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def _refuse(self, code):
        # Accept first, then close: closing before accept() rejects the
        # handshake (HTTP 403) and browsers then only ever see code 1006.
        await self.accept()
        await self.close(code=code)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if not isinstance(payload, dict):
            return
        text = payload.get('text')
        text = text.strip() if isinstance(text, str) else ''
        if not text:
            return
        if len(text) > MAX_MESSAGE_LENGTH:
            await self.send(text_data=json.dumps(
                {'error': 'too_long', 'max_length': MAX_MESSAGE_LENGTH}
            ))
            return

        message = await self._save_message(
            self.course_id, self.user_id, self.other_user_id, text
        )

        await self.channel_layer.group_send(
            self.group_name,
            {'type': 'chat.message', 'message': message},
        )
        # The receiver's bell and unread counts (NotificationConsumer).
        await self.channel_layer.group_send(
            user_group(self.other_user_id),
            {'type': 'notify', 'event': new_message_event(message)},
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event['message']))

    @database_sync_to_async
    def _verify_participants(self, course_id, user_id, other_user_id):
        # Same rule as POST /api/messages/ (api/chat.py).
        return chat_allowed(course_id, user_id, other_user_id)

    @database_sync_to_async
    def _save_message(self, course_id, sender_id, receiver_id, text):
        from .models import Message
        from .serializers import MessageSerializer

        msg = Message.objects.create(
            sender_id=sender_id,
            receiver_id=receiver_id,
            course_id=course_id,
            text=text,
        )
        return MessageSerializer(msg).data


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    A user's own notification socket: ws/notifications/?token=<jwt>.

    Joins group user_<id> (chat.user_group); the server sends {"type": ...}
    events there: new_message (chat.new_message_event) when someone writes to
    this user, read when this user marked a conversation read (other tabs).
    Close code 4001 when not logged in, as for the chat. Nothing is received.
    """

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            # Accept, then close: a browser only sees the code that way.
            await self.accept()
            await self.close(code=4001)
            return
        self.group_name = user_group(user.id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify(self, event):
        await self.send(text_data=json.dumps(event['event']))
