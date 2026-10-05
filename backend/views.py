"""
Server-rendered public pages (landing now; course and legal pages later).

Templates live in backend/templates/public/, styles in backend/static/public/.
The React app is served separately by spa_view / lesson_view in backend/urls.py.
"""

from decimal import Decimal

from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from api.models import Course

NBSP = ' '


def format_rub(value):
    """Format a ruble amount as "1 990 ₽" (non-breaking spaces).

    price/old_price are DecimalField(decimal_places=2). Whole amounts drop the
    kopecks; non-integer amounts show them with a decimal comma ("1 990,50 ₽")
    rather than being rounded, so the card never misstates what is charged.

    Done here rather than with intcomma so the price reads the same on / and /en/,
    and because backend/ is not an installed app (no templatetags).
    """
    value = Decimal(value).quantize(Decimal('0.01'))
    rubles, kopecks = divmod(value, 1)
    text = f'{int(rubles):,}'.replace(',', NBSP)
    if kopecks:
        text += ',' + f'{kopecks:.2f}'[2:]
    return f'{text}{NBSP}₽'


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
        course.price_label = format_rub(course.price)
        course.old_price_label = (
            format_rub(course.old_price)
            if course.old_price is not None and course.old_price > course.price
            else ''
        )
    return render(request, 'public/landing.html', {'courses': courses})


def course_detail_view(request, slug):
    """Course page. Placeholder template for now; step 4 replaces it (keep URL name)."""
    course = get_object_or_404(Course, slug=slug, is_published=True)
    return render(request, 'public/course_detail.html', {'course': course})
