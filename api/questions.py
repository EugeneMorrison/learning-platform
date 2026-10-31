"""
«Задать вопрос»: a student's question about one task, sent to the course author
in their private chat (views.QuestionView) with a snapshot of the task and of
the student's work at that moment. The snapshot is built here, on the server,
from what the student may see (block_content.student_content): never the
solution, hidden tests, hidden header/footer code, correct_answer or the FILL
answers.

Context shape (Message.context):
    course:     {id, title}
    lesson:     {id, title}
    block:      {id, type}
    task:       CODE {prompt, starter_code} · QUIZ {question, options} ·
                FILL {prompt, template (gaps blanked)}
    submission: the latest recorded submission, or null:
                CODE {code, language} · QUIZ {option: the chosen option's text} ·
                FILL {blanks}; all with is_correct and submitted_at
    draft:      CODE only, optional: {code, language}, the editor's code as the
                student had it (not submitted)
"""

from .block_content import student_content
from .models import Attempt, Progress
from .quiz_state import saved_quiz_snapshot

# CODE runs Python only; the student's chosen Python version isn't stored.
CODE_LANGUAGE = 'Python'

# Longest editor draft accepted with a question, in characters (code points).
MAX_DRAFT_LENGTH = 20000


def task_view(block):
    """The task as the student sees it: only the fields that state it, taken
    from student_content() (so nothing hidden can get in)."""
    content = student_content(block.type, block.content)
    if block.type == 'CODE':
        return {'prompt': content.get('prompt', ''), 'starter_code': content.get('starter_code', '')}
    if block.type == 'QUIZ':
        return {'question': content.get('question', ''), 'options': list(content.get('options') or [])}
    return {'prompt': content.get('prompt', ''), 'template': content.get('template', '')}


def latest_submission(block, student):
    """The student's latest recorded submission (an Attempt; Progress for work
    saved before attempts were kept), in the context's shape, or None."""
    # No id tie-break: Attempt ids are UUIDs, not in creation order. Real
    # submissions (graded on the server) are never saved in the same instant.
    attempt = Attempt.objects.filter(student=student, block=block).order_by('-created_at').first()
    if attempt is not None:
        answer, is_correct, when = attempt.answer, attempt.is_correct, attempt.created_at
    else:
        progress = Progress.objects.filter(student=student, block=block).first()
        if progress is None or not isinstance(progress.answer, dict):
            return None
        answer, is_correct, when = progress.answer, progress.is_correct, progress.completed_at
    answer = answer if isinstance(answer, dict) else {}
    base = {'is_correct': is_correct, 'submitted_at': when.isoformat() if when else None}

    if block.type == 'CODE':
        return {**base, 'code': answer.get('code') or '', 'language': CODE_LANGUAGE}
    if block.type == 'QUIZ':
        snapshot = saved_quiz_snapshot(answer) if is_correct is True else None
        options = snapshot['options'] if snapshot is not None else block.content.get('options') or []
        selected = answer.get('selected')
        if isinstance(selected, list):
            chosen = [options[index] for index in selected
                      if type(index) is int and 0 <= index < len(options)]
            return {**base, 'option': '<br />'.join(chosen) if chosen else None}
        valid = isinstance(selected, int) and not isinstance(selected, bool) and 0 <= selected < len(options)
        return {**base, 'option': options[selected] if valid else None}
    return {**base, 'blanks': list(answer.get('blanks') or [])}


def build_context(block, student, draft=None):
    """The snapshot attached to a question (see the module docstring). `draft`
    (CODE only) is left out when empty or the same as the latest submitted code
    or the starter code."""
    lesson = block.lesson
    course = lesson.course
    submission = latest_submission(block, student)
    context = {
        'course': {'id': str(course.id), 'title': course.title},
        'lesson': {'id': str(lesson.id), 'title': lesson.title},
        'block': {'id': str(block.id), 'type': block.type},
        'task': task_view(block),
        'submission': submission,
    }
    if block.type == 'QUIZ':
        progress = Progress.objects.filter(student=student, block=block, is_correct=True).first()
        snapshot = saved_quiz_snapshot(progress.answer) if progress is not None else None
        if snapshot is not None:
            context['task'] = {'question': snapshot['question'], 'options': snapshot['options']}
    if block.type == 'CODE' and draft and draft.strip():
        same_as = {(block.content.get('starter_code') or '').strip()}
        if submission:
            same_as.add(submission['code'].strip())
        if draft.strip() not in same_as:
            context['draft'] = {'code': draft, 'language': CODE_LANGUAGE}
    return context
