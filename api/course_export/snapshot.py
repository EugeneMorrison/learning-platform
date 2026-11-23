"""Read an ordered snapshot of course content. Never load student records."""
from uuid import UUID

from django.db import transaction
from django.db.models import F, Prefetch

from api.block_content import normalize_test, student_content
from api.models import Block, Course, Lesson


STEP_NAMES = {
    'TEXT': 'text', 'QUIZ': 'choice', 'CODE': 'code', 'FILL': 'fill-blanks',
    'SORT': 'sorting', 'MATCH': 'matching', 'TABLE': 'table',
}
LEARNER_FIELDS = {
    'TEXT': ('html',),
    'QUIZ': ('question', 'options', 'multiple_answers', 'shuffle_options'),
    'CODE': ('prompt', 'starter_code', 'tests', 'hidden_test_count', 'output_comparison'),
    'FILL': ('prompt', 'template', 'case_sensitive'),
    'SORT': ('prompt', 'items', 'html'),
    'MATCH': ('prompt', 'left', 'right', 'html', 'keep_left_order'),
    'TABLE': ('prompt', 'rows', 'columns', 'multiple_answers', 'shuffle_rows', 'shuffle_columns', 'any_answer_correct'),
}


def learner_content(block):
    # Filter both the native answer-bearing fields and any unknown extension
    # fields. In particular, never serialize arbitrary keys from a test case.
    visible = student_content(block.type, block.content)
    result = {key: visible[key] for key in LEARNER_FIELDS[block.type] if key in visible}
    if block.type == 'CODE':
        result['tests'] = []
        for example in visible['tests']:
            stdin, expected = normalize_test(example)
            result['tests'].append({'input': stdin, 'expected': expected})
    return result


def metadata(obj, fields):
    return {'id': str(obj.pk), 'created_at': obj.created_at.isoformat(), 'updated_at': obj.updated_at.isoformat(),
            **{field: getattr(obj, field) for field in fields}}


@transaction.atomic
def extract_course(identifier, author_materials, warn):
    try:
        key = UUID(identifier)
    except ValueError:
        key = None
    lessons = Lesson.objects.order_by('order_index', 'pk').prefetch_related(
        Prefetch('blocks', queryset=Block.objects.order_by('order_index', 'pk')))
    courses = Course.objects.annotate(author_username=F('author__username')).prefetch_related(
        Prefetch('lessons', queryset=lessons))
    course = courses.filter(pk=key).first() if key else None
    if course is None:
        course = courses.get(slug=identifier)
    result = metadata(course, ('slug', 'title', 'description', 'tagline', 'tag', 'price', 'old_price',
                               'sort_order', 'level', 'stepik_id', 'author_id', 'is_published'))
    result['cover'] = course.cover.name or None
    result['audience'] = 'author' if author_materials else 'learner'
    result['author_username'] = course.author_username
    result['lessons'] = []
    for lesson in course.lessons.all():
        row = metadata(lesson, ('title', 'order_index', 'is_preview'))
        row['steps'] = []
        result['lessons'].append(row)
        for block in lesson.blocks.all():
            step = metadata(block, ('type', 'order_index'))
            if block.type not in STEP_NAMES:
                warn(f"Lesson {lesson.pk}, step {block.pk}: unsupported type {block.type}")
            if author_materials:
                step['content'] = block.content
            elif block.type in STEP_NAMES:
                try:
                    step['content'] = learner_content(block)
                except (TypeError, KeyError, AttributeError, ValueError):
                    warn(f"Lesson {lesson.pk}, step {block.pk}: unreadable exercise configuration")
                    step['content'] = None
            else:
                step['content'] = None
            row['steps'].append(step)
    return result
