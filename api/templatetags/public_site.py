"""Template tags for the public (Django-rendered) pages."""

from django import template
from django.conf import settings
from django.utils import translation

from api.models import Review

register = template.Library()


def get_brand_name(lang=None):
    """The site name in `lang` (default: the active language) from
    settings.BRAND_NAMES; Russian for a language it doesn't list."""
    lang = (lang or translation.get_language() or settings.LANGUAGE_CODE).split('-')[0]
    return settings.BRAND_NAMES.get(lang, settings.BRAND_NAMES[settings.LANGUAGE_CODE])


@register.simple_tag
def brand_name():
    """The site name for the logo, footer and page titles: {% brand_name %}."""
    return get_brand_name()


@register.inclusion_tag('public/includes/brand_logo.html')
def brand_logo():
    """The header logo: {% brand_logo %}. The name is split at «Ё», whose dots
    become the cat's eyes (static/public/css/brand-logo.css); a name without
    «Ё» (English) is rendered as plain text, as before."""
    name = get_brand_name()
    before, yo, after = name.partition('Ё')
    return {'name': name, 'before': before, 'yo': yo, 'after': after}


@register.simple_tag(takes_context=True)
def reviews_published(context):
    """Whether the landing page's "Отзывы" section has content (used by the header
    link in base.html). Reuses the landing view's `reviews` list when the page
    has one; other pages run a single EXISTS query."""
    if 'reviews' in context:
        return bool(context['reviews'])
    return Review.objects.filter(is_published=True).exists()
