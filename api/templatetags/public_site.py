"""Template tags for the public (Django-rendered) pages."""

from django import template
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from api.models import Review

register = template.Library()

# The site name and tagline, the only place the Django templates take them from
# (the React app has its own constants in frontend/src/brand.js). Translated like
# any other string.
BRAND_NAME = _('Game Python')
BRAND_TAGLINE = _('от ужаса до понимания')


@register.simple_tag
def brand_name():
    """The short site name for the logo and footer: {% brand_name %}."""
    return BRAND_NAME


@register.simple_tag
def brand_title():
    """Default page <title>: "Game Python — от ужаса до понимания"."""
    return format_lazy('{} — {}', BRAND_NAME, BRAND_TAGLINE)


@register.simple_tag(takes_context=True)
def reviews_published(context):
    """Whether the landing page's "Отзывы" section has content (used by the header
    link in base.html). Reuses the landing view's `reviews` list when the page
    has one; other pages run a single EXISTS query."""
    if 'reviews' in context:
        return bool(context['reviews'])
    return Review.objects.filter(is_published=True).exists()
