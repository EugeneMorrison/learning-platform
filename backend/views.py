"""
Server-rendered public pages (landing and course pages; legal pages later).

Templates live in backend/templates/public/, styles in backend/static/public/.
The React app is served separately by spa_view / lesson_view in backend/urls.py.
"""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from api.models import Course

from .pricing import add_price_labels

# Block types counted on the course page, as (Block.type, annotation name).
BLOCK_COUNTS = [
    ('TEXT', 'text_count'),
    ('QUIZ', 'quiz_count'),
    ('CODE', 'code_count'),
    ('FILL', 'fill_count'),
]


def landing_view(request):
    """Landing page: Russian at /, English at /en/ (see i18n_patterns in urls.py)."""
    # Explicit order_by: Meta.ordering is ['sort_order', '-created_at'], the landing
    # wants title as the tiebreak. annotate() gives lesson counts in the same query.
    courses = list(
        Course.objects.filter(is_published=True)
        .annotate(lesson_count=Count('lessons'))
        .order_by('sort_order', 'title')
    )
    for course in courses:
        add_price_labels(course)
    return render(request, 'public/landing.html', {'courses': courses})


def course_detail_view(request, slug):
    """Course sales page with the open syllabus. 404 for unpublished or missing courses."""
    course = add_price_labels(get_object_or_404(Course, slug=slug, is_published=True))

    # One query for the whole syllabus. values() keeps the context to titles and
    # integer counts: block content (answers, solutions, tests) never reaches the
    # template.
    lessons = list(
        course.lessons.order_by('order_index')
        .annotate(**{
            name: Count('blocks', filter=Q(blocks__type=block_type))
            for block_type, name in BLOCK_COUNTS
        })
        .values('title', *(name for _, name in BLOCK_COUNTS))
    )
    totals = {
        name: sum(lesson[name] for lesson in lessons) for _, name in BLOCK_COUNTS
    }

    return render(request, 'public/course_detail.html', {
        'course': course,
        'lessons': lessons,
        'totals': totals,
    })
