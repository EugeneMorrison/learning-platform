"""
Server-rendered public pages (landing, course catalog, course and about pages;
legal pages later).

Templates live in backend/templates/public/, styles in backend/static/public/.
The React app is served separately by spa_view / lesson_view in backend/urls.py.
"""

from datetime import timezone

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


def published_courses():
    """Published courses for the catalogs (landing, /courses/), with lesson_count
    and price labels, in the author's order: sort_order, then title. Explicit
    order_by: Meta.ordering is ['sort_order', '-created_at']. One query."""
    courses = list(
        Course.objects.filter(is_published=True)
        .annotate(lesson_count=Count('lessons'))
        .order_by('sort_order', 'title')
    )
    for course in courses:
        add_price_labels(course)
    return courses


def normalize_title(title):
    """Title as the /courses/ search compares it: lower case, ё = е, single
    spaces. public/js/catalog.js normalizes the typed query the same way."""
    return ' '.join(title.lower().replace('ё', 'е').split())


def landing_view(request):
    """Landing page: Russian at /, English at /en/ (see i18n_patterns in urls.py)."""
    courses = published_courses()

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


def courses_view(request):
    """Course catalog (/courses/, /en/courses/): every published course as a card,
    in the author's order. Search, filters and sorting run in the browser
    (public/js/catalog.js) on the data-* attributes set here; without JS the page
    is the full list."""
    courses = published_courses()
    for course in courses:
        course.search_title = normalize_title(course.title)
        # Fixed-width UTC timestamp: string order is time order for the script.
        course.created_key = course.created_at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    return render(request, 'public/courses.html', {'courses': courses})


def about_view(request):
    """"Обо мне" (/about/): the author hero (public/includes/hero.html) and the bio,
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
