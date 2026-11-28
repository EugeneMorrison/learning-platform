"""
Server-rendered public pages (landing, course catalog, course and about pages;
legal pages later).

Templates live in backend/templates/public/, styles in backend/static/public/.
The React app is served separately by spa_view / lesson_view in backend/urls.py.
"""

from datetime import timezone

from django.contrib.staticfiles import finders
from django.db.models import Avg, Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils import translation

from api.block_content import normalize_test, student_content
from api.models import Course, Enrollment, Lesson, Review

from .pricing import NBSP, add_price_labels

# Card text cut from the description when a course has no tagline: about two
# lines of a card (CSS clamps it to two lines anyway).
CARD_SUMMARY_CHARS = 160

# Block types counted on the course page, as (Block.type, annotation name).
BLOCK_COUNTS = [
    ('TEXT', 'text_count'),
    ('QUIZ', 'quiz_count'),
    ('CODE', 'code_count'),
    ('FILL', 'fill_count'),
    ('SORT', 'sort_count'),
    ('MATCH', 'match_count'),
    ('TABLE', 'table_count'),
]


def published_courses():
    """Published courses for the catalogs (landing, /courses/) in the author's
    order (sort_order, then title; explicit, as Meta.ordering is ['sort_order',
    '-created_at']), with what the card shows (public/includes/course_card.html):
    lesson_count, student_count / students_label, card_summary and price labels.

    One query. Students come from a correlated subquery: a second Count over a
    join would multiply the rows by the lessons (lessons x students)."""
    students = (
        Enrollment.objects.filter(course=OuterRef('pk'))
        .order_by().values('course').annotate(n=Count('*')).values('n')
    )
    courses = list(
        Course.objects.filter(is_published=True)
        .annotate(
            lesson_count=Count('lessons'),
            student_count=Coalesce(Subquery(students, output_field=IntegerField()), 0),
        )
        .order_by('sort_order', 'title')
    )
    for course in courses:
        add_price_labels(course)
        course.students_label = format_count(course.student_count)
        course.card_summary = card_summary(course)
    return courses


def format_count(n):
    """A whole number with non-breaking spaces between thousands: "1 234",
    the same in RU and EN (like the prices, backend/pricing.py)."""
    return f'{n:,}'.replace(',', NBSP)


def card_summary(course):
    """The card's text: the tagline, else the start of the description (plain
    text typed by the author) on one line, cut at a word boundary with "…".
    Empty when both are empty."""
    if course.tagline.strip():
        return course.tagline.strip()
    text = ' '.join(course.description.split())
    if len(text) <= CARD_SUMMARY_CHARS:
        return text
    head = text[:CARD_SUMMARY_CHARS + 1]  # +1: a space right after the limit is a boundary
    cut = head.rsplit(' ', 1)[0] if ' ' in head else text[:CARD_SUMMARY_CHARS]
    return cut.rstrip(' .,;:!?—-') + '…'


def normalize_title(title):
    """Title as the /courses/ search compares it: lower case, ё = е, single
    spaces. public/js/catalog.js normalizes the typed query the same way."""
    return ' '.join(title.lower().replace('ё', 'е').split())


def landing_view(request):
    """Landing page (/)."""
    courses = published_courses()

    # Reviews are edited in the Django admin; the section is hidden while there
    # are none. Text in the active language (always Russian for now).
    lang = translation.get_language()
    reviews = list(Review.objects.filter(is_published=True).select_related('course'))
    for review in reviews:
        review.text = review.text_for(lang)

    return render(request, 'public/landing.html', {
        'courses': courses,
        'reviews': reviews,
    })


def courses_view(request):
    """Course catalog (/courses/): every published course as a card,
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

    # Fetch syllabus metadata in one query without loading block content.
    lessons = list(
        course.lessons.order_by('order_index')
        .annotate(**{
            name: Count('blocks', filter=Q(blocks__type=block_type))
            for block_type, name in BLOCK_COUNTS
        })
        .values('id', 'title', 'is_preview', *(name for _, name in BLOCK_COUNTS))
    )
    totals = {
        name: sum(lesson[name] for lesson in lessons) for _, name in BLOCK_COUNTS
    }

    return render(request, 'public/course_detail.html', {
        'course': course,
        'lessons': lessons,
        'totals': totals,
        'student_reviews': course.student_reviews.filter(status='approved').select_related('student').order_by('-published_at'),
        'average_rating': course.student_reviews.filter(status='approved').aggregate(value=Avg('rating'))['value'],
    })


def lesson_preview_view(request, slug, lesson_id):
    lesson = get_object_or_404(
        Lesson.objects.select_related('course'), pk=lesson_id, course__slug=slug,
        course__is_published=True, course__price__gt=0, is_preview=True,
    )
    blocks = []
    for block in lesson.blocks.order_by('order_index'):
        task = student_content(block.type, block.content)
        if block.type == 'CODE':
            task['examples'] = [normalize_test(test) for test in task['tests']]
        elif block.type == 'FILL':
            task['template'] = task['template'].replace('{{}}', '____')
        blocks.append({'type': block.type, 'task': task})
    return render(request, 'public/lesson_preview.html', {'lesson': lesson, 'blocks': blocks})
