"""Template tags for the public (Django-rendered) pages."""

from django import template

from api.models import Review

register = template.Library()


@register.simple_tag(takes_context=True)
def reviews_published(context):
    """Whether the landing page's "Отзывы" section has content (used by the header
    link in base.html). Reuses the landing view's `reviews` list when the page
    has one; other pages run a single EXISTS query."""
    if 'reviews' in context:
        return bool(context['reviews'])
    return Review.objects.filter(is_published=True).exists()
