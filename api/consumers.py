"""
WebSocket consumer for course chat.

Conversation model: a chat exists between two users (e.g. teacher ↔ student)
within a single course. Both sides connect with the SAME (course_id, other_user_id)
pair but each from their own perspective. We derive a stable group name from
the sorted user-id pair so both sockets end up in the same group regardless
of who initiated.

URL: ws/chat/<course_id>/<other_user_id>/?token=<jwt>
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.course_id = self.scope['url_route']['kwargs']['course_id']
        self.other_user_id = int(self.scope['url_route']['kwargs']['other_user_id'])
        self.user_id = user.id

        # Verify this user is allowed to chat in this course with this other user.
        allowed = await self._verify_participants(
            self.course_id, self.user_id, self.other_user_id
        )
        if not allowed:
            await self.close(code=4003)
            return

        a, b = sorted([self.user_id, self.other_user_id])
        self.group_name = f'chat_{self.course_id}_{a}_{b}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

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

        text = (payload.get('text') or '').strip()
        if not text:
            return

        message = await self._save_message(
            self.course_id, self.user_id, self.other_user_id, text
        )

        await self.channel_layer.group_send(
            self.group_name,
            {'type': 'chat.message', 'message': message},
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event['message']))

    @database_sync_to_async
    def _verify_participants(self, course_id, user_id, other_user_id):
        from .models import Course, Enrollment

        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return False

        # User must be either the course author or an enrolled student.
        # Other user must also be either the author or an enrolled student.
        def role(uid):
            if course.author_id == uid:
                return 'author'
            if Enrollment.objects.filter(course=course, student_id=uid).exists():
                return 'student'
            return None

        my_role = role(user_id)
        other_role = role(other_user_id)
        if my_role is None or other_role is None:
            return False
        # Only teacher↔student conversations allowed (not student↔student).
        return {my_role, other_role} == {'author', 'student'}

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
