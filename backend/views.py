"""
Server-rendered public pages (landing, course and about pages; legal pages later).

Templates live in backend/templates/public/, styles in backend/static/public/.
The React app is served separately by spa_view / lesson_view in backend/urls.py.
"""

from django.contrib.staticfiles import finders
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils import translation

from api.models import Course, Review

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

    # Reviews are edited in the Django admin; the section is hidden while there
    # are none. /en/ shows the English text, falling back to Russian.
    lang = translation.get_language()
    reviews = list(Review.objects.filter(is_published=True).select_related('course'))
    for review in reviews:
        review.text = review.text_for(lang)

    return render(request, 'public/landing.html', {
        'courses': courses,
        'reviews': reviews,
    })


def about_view(request):
    """"Об авторе": the author hero (public/includes/hero.html) and the bio,
    both in the template (public/about.html)."""
    return render(request, 'public/about.html')


def favicon_view(request):
    """/favicon.ico at the site root: browsers request it without any <link>, and
    the React catch-all would otherwise answer with index.html. Serves the same
    file the pages link by its hashed static name (public/img/favicon.ico)."""
    path = finders.find('public/img/favicon.ico')
    if not path:
        raise Http404
    response = FileResponse(open(path, 'rb'), content_type='image/x-icon')
    response['Cache-Control'] = 'public, max-age=86400'  # a day: the name never changes
    return response


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
