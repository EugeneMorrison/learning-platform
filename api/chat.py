"""
Rules shared by the chat WebSocket consumer (consumers.py) and the REST
endpoint POST /api/messages/ (views.MessageView), so both accept exactly the
same conversations and message sizes.
"""

import uuid

# Longest message, in characters (code points). The React chat window uses the
# same number (frontend/src/lib/chatSocket.js).
MAX_MESSAGE_LENGTH = 2000


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
