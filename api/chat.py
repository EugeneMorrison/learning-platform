"""
Rules shared by the chat WebSocket consumer (consumers.py) and the REST
endpoints POST /api/messages/ (views.MessageView) and POST /api/questions/
(views.QuestionView), so all accept exactly the same conversations and message
sizes and deliver to the same per-conversation group.
"""

import uuid

# Longest message, in characters (code points). The React chat window uses the
# same number (frontend/src/lib/chatSocket.js).
MAX_MESSAGE_LENGTH = 2000


def chat_group(course_id, user_id, other_user_id):
    """The channel-layer group of one conversation. Both sides get the same
    name whoever opened it: course + the sorted pair of user ids."""
    a, b = sorted([int(user_id), int(other_user_id)])
    return f'chat_{course_id}_{a}_{b}'


def user_group(user_id):
    """The channel-layer group of one user's notification sockets
    (ws/notifications/, NotificationConsumer): every tab they have open."""
    return f'user_{int(user_id)}'


PREVIEW_LENGTH = 80


def message_preview(text):
    """The start of a message as one line of plain text (notifications)."""
    text = ' '.join((text or '').split())
    return text if len(text) <= PREVIEW_LENGTH else text[:PREVIEW_LENGTH - 1].rstrip() + '…'


def new_message_event(data):
    """The notification for a saved message (MessageSerializer data), sent to
    its receiver's user group."""
    return {
        'type': 'new_message',
        'message_id': data['id'],
        'course_id': str(data['course']),
        'sender_id': data['sender'],
        'sender_name': data['sender_name'],
        'is_question': data.get('context') is not None,
        'preview': message_preview(data['text']),
        'created_at': str(data['created_at']),
    }


def notify_user(user_id, event):
    """Send `event` (a dict with a "type") to the user's notification sockets."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(user_group(user_id), {'type': 'notify', 'event': event})


def push_message(message):
    """Deliver a saved Message to the open chat sockets of its two users (the
    same frame the consumer sends), notify its receiver (new_message_event),
    and return its serialized data. For messages saved outside the consumer:
    POST /api/messages/, /api/questions/."""
    import json

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from django.core.serializers.json import DjangoJSONEncoder
    from .serializers import MessageSerializer

    # JSON-safe (UUIDs, datetimes as strings): the consumer json.dumps the frame.
    data = json.loads(json.dumps(MessageSerializer(message).data, cls=DjangoJSONEncoder))
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(
            chat_group(message.course_id, message.sender_id, message.receiver_id),
            {'type': 'chat.message', 'message': data},
        )
    notify_user(message.receiver_id, new_message_event(data))
    return data


def is_valid_course_id(course_id):
    try:
        uuid.UUID(str(course_id))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def chat_allowed(course_id, user_id, other_user_id):
    """
    True when the two users may chat in this course: one of them is the
    course author, the other an enrolled student (no student↔student, no
    outsiders, no chatting with yourself). An unknown or malformed course id
    is simply not allowed.
    """
    from .models import Course, Enrollment

    if not is_valid_course_id(course_id):
        return False
    try:
        user_id, other_user_id = int(user_id), int(other_user_id)
    except (TypeError, ValueError):
        return False
    course = Course.objects.filter(id=course_id).first()
    if course is None:
        return False

    def role(uid):
        if course.author_id == uid:
            return 'author'
        if Enrollment.objects.filter(course=course, student_id=uid).exists():
            return 'student'
        return None

    return {role(user_id), role(other_user_id)} == {'author', 'student'}
