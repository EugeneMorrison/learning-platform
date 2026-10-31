"""QUIZ-only display metadata and first-success persistence.

Indices still refer to the author's options, never to display positions.
Snapshots are constructed from an explicit public-field allowlist, not from
request data or from the complete block content.
"""

import copy

from django.db import models, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ParseError

from .block_content import grade_quiz
from .models import Attempt, Block, Progress


def saved_quiz_snapshot(answer):
    if not isinstance(answer, dict):
        return None
    snapshot = answer.get('quiz_snapshot')
    if not isinstance(snapshot, dict):
        return None
    if (not isinstance(snapshot.get('question'), str)
            or not isinstance(snapshot.get('options'), list)
            or not all(isinstance(option, str) for option in snapshot['options'])):
        return None
    # Never forward unrecognized fields, even from older stored JSON.
    public = {'question': snapshot['question'], 'options': list(snapshot['options'])}
    if snapshot.get('multiple_answers') is True:
        public['multiple_answers'] = True
    if isinstance(snapshot.get('explanation'), str):
        public['explanation'] = snapshot['explanation']
    return public


def prepare_quiz_answer(block, raw_answer):
    if not isinstance(raw_answer, dict):
        raise ParseError('Укажите выбранный вариант ответа.')
    selected = raw_answer.get('selected')
    options = block.content.get('options') or []
    if block.content.get('multiple_answers') is True:
        valid = (isinstance(selected, list) and bool(selected)
                 and all(type(index) is int and 0 <= index < len(options) for index in selected)
                 and len(set(selected)) == len(selected))
    else:
        valid = type(selected) is int and 0 <= selected < len(options)
    if not valid:
        raise ParseError('Выбран недопустимый вариант ответа. Обновите урок.')
    answer = {'selected': selected}
    has_order = 'display_order' in raw_answer
    has_revision = 'quiz_revision' in raw_answer
    if has_order != has_revision:
        raise ParseError('Не указан порядок вариантов или версия задания. Обновите урок.')
    if has_order:
        order = raw_answer['display_order']
        if (not isinstance(order, list) or len(order) != len(options)
                or any(type(index) is not int for index in order)
                or sorted(order) != list(range(len(options)))):
            raise ParseError('Недопустимый порядок вариантов ответа. Обновите урок.')
        revision = raw_answer['quiz_revision']
        try:
            when = parse_datetime(revision) if isinstance(revision, str) else None
        except ValueError:
            when = None
        if when is None or when != block.updated_at:
            raise ParseError('Автор изменил задание. Обновите урок и ответьте ещё раз.')
        answer['display_order'] = list(order)
    correct = grade_quiz(block.content, answer)
    # Old clients lack the displayed permutation: preserve their answer shape
    # and use the deterministic legacy fallback when restoring completed work.
    if correct and has_order:
        snapshot = {'question': block.content.get('question', ''), 'options': copy.deepcopy(options)}
        if block.content.get('multiple_answers') is True:
            snapshot['multiple_answers'] = True
        explanation = block.content.get('explanation')
        if isinstance(explanation, str) and explanation:
            snapshot['explanation'] = explanation
        answer['quiz_snapshot'] = snapshot
    return answer, correct


def submit_quiz(user, block, raw_answer):
    """Validate against fresh content; a recorded correct answer is immutable.

    Locking the block also serializes against author edits on databases with
    row locks. The conditional progress UPDATE protects the first success
    independently of row-lock support. A failed transaction records no attempt.
    """
    with transaction.atomic():
        block = Block.objects.select_for_update().get(pk=block.pk)
        answer, correct = prepare_quiz_answer(block, raw_answer)
        progress, _ = Progress.objects.get_or_create(
            student=user, block=block, defaults={'lesson': block.lesson},
        )
        now = timezone.now()
        recorded = Progress.objects.filter(pk=progress.pk).exclude(is_correct=True).update(
            lesson=block.lesson, completed=True, answer=answer, is_correct=correct,
            attempts=models.F('attempts') + 1, completed_at=now, updated_at=now,
        )
        if recorded:
            Attempt.objects.create(student=user, block=block, answer=answer, is_correct=correct)
            progress.refresh_from_db()
        else:
            # Practice reports this attempt's verdict without mutating saved work.
            progress = Progress(student=user, block=block, lesson=block.lesson,
                                answer=answer, is_correct=correct, completed=True)
        return progress, bool(recorded)
