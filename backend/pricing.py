"""
Price display helpers shared by the public pages (landing cards, course page).
"""

from decimal import Decimal

NBSP = ' '


def format_rub(value):
    """Format a ruble amount as "1 990 ₽" (non-breaking spaces).

    price/old_price are DecimalField(decimal_places=2). Whole amounts drop the
    kopecks; non-integer amounts show them with a decimal comma ("1 990,50 ₽")
    rather than being rounded, so the page never misstates what is charged.

    Done here rather than with intcomma so the price reads the same on / and /en/,
    and because backend/ is not an installed app (no templatetags).
    """
    value = Decimal(value).quantize(Decimal('0.01'))
    rubles, kopecks = divmod(value, 1)
    text = f'{int(rubles):,}'.replace(',', NBSP)
    if kopecks:
        text += ',' + f'{kopecks:.2f}'[2:]
    return f'{text}{NBSP}₽'


def add_price_labels(course):
    """Attach price_label and old_price_label (empty unless old_price > price)."""
    course.price_label = format_rub(course.price)
    course.old_price_label = (
        format_rub(course.old_price)
        if course.old_price is not None and course.old_price > course.price
        else ''
    )
    return course
