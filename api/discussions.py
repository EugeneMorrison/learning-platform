"""
Discussions: public threads about one task block (Stepik-style), next to the
private chat with the course author (api/chat.py), which they don't touch.

Who reads what is one rule, Thread.objects.visible_to (api/models.py): the
course author and its enrolled students only; on a block the viewer hasn't
solved yet, only the pinned threads and their own. Anything outside it is a
404, as for lessons and blocks.

Text is plain text: stored as typed (stripped), never turned into HTML; the
React panel renders it as a text node.

Who may do what (views.Thread*View):
    start a thread, reply   anyone who can read the block / the thread
    resolve / reopen        the thread's starter, the course author
    pin / unpin             the course author
    delete a comment        the course author (soft: Comment.is_deleted)
    delete a thread         the course author (with all its comments)
    report a comment        anyone who can read it but its writer and the
                            course author (once; the author sees open reports)
    ban / unban a user      the course author, for all her courses: a banned
                            user can read but not post (DiscussionBan)
"""

import math
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied, Throttled

from .models import Block, Comment, CommentReport, DiscussionBan, Progress

# Longest post, in characters (code points); the panel uses the same number
# (frontend/src/components/DiscussionPanel.jsx).
MAX_COMMENT_LENGTH = 2000

# One post (new thread or reply) per this many seconds per user, anywhere;
# the course author is exempt in her own courses.
POST_INTERVAL_SECONDS = 60


def is_course_author(user, block):
    return block.lesson.course.author_id == user.id


def can_see_all(user, block):
    """Every thread on the block, not only the pinned and own ones."""
    return block.type == 'TEXT' or is_course_author(user, block) or Progress.objects.filter(
        student=user, block=block, is_correct=True).exists()


def discussion_block(user, block_id):
    """The block whose discussion the user may read and join; 404 outside
    the user's content access."""
    block = (Block.objects.visible_to(user).select_related('lesson__course')
             .filter(pk=block_id).first())
    if block is None:
        raise NotFound(gettext('Задание не найдено.'))
    return block


def clean_text(value):
    """The post's text, stripped; 400 when empty or too long."""
    text = value.strip() if isinstance(value, str) else ''
    if not text:
        raise ParseError(gettext('Напишите сообщение.'))
    if len(text) > MAX_COMMENT_LENGTH:
        raise ParseError(
            gettext('Сообщение слишком длинное: не больше %(max)d символов.') % {'max': MAX_COMMENT_LENGTH}
        )
    return text


def is_banned(user, block):
    """The course author has banned the user from posting (in all her courses)."""
    return DiscussionBan.objects.filter(author_id=block.lesson.course.author_id, user=user).exists()


def check_not_banned(user, block):
    if is_banned(user, block):
        raise PermissionDenied(gettext('Автор курса закрыл вам возможность писать в обсуждения.'))


def open_reports():
    """Reports the course author still has to look at: not dismissed, on a
    comment that is still there."""
    return CommentReport.objects.filter(is_dismissed=False, comment__is_deleted=False)


def check_post_interval(user, block):
    """429 (with Retry-After) when the user posted less than a minute ago.
    Read from the user's latest Comment, so it holds across processes and
    restarts. The course author is not limited in her course."""
    if is_course_author(user, block):
        return
    last = (Comment.objects.filter(user=user).order_by('-created_at')
            .values_list('created_at', flat=True).first())
    if last is None:
        return
    wait = (last + timedelta(seconds=POST_INTERVAL_SECONDS) - timezone.now()).total_seconds()
    if wait > 0:
        seconds = math.ceil(wait)
        exc = Throttled(detail=gettext(
            'Писать в обсуждения можно не чаще раза в минуту. Попробуйте через %(seconds)d с.'
        ) % {'seconds': seconds})
        exc.wait = seconds  # → Retry-After
        raise exc
