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


# A paragraph that is one short line without closing punctuation, followed by
# more text, reads as a subheading ("Опыт", "Чему я учу").
SUBHEADING_MAX_CHARS = 60
SENTENCE_END = ('.', '!', '?', '…', ',', ';')


@register.filter(needs_autoescape=True)
def paragraphs_with_subheadings(value, autoescape=True):
    """
    Like Django's linebreaks (escape, blank lines → <p>, single newlines → <br>),
    except that a short standalone line followed by more text becomes an
    <h3 class="author__subheading">. Tags are chosen here; every piece of text is
    escaped, so author input can never inject HTML.
    """
    from django.utils.html import conditional_escape
    from django.utils.safestring import mark_safe
    import re

    esc = conditional_escape if autoescape else (lambda s: s)
    text = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]

    html = []
    for i, para in enumerate(paras):
        is_subheading = (
            '\n' not in para
            and len(para) <= SUBHEADING_MAX_CHARS
            and not para.endswith(SENTENCE_END)
            and i < len(paras) - 1
        )
        if is_subheading:
            html.append(f'<h3 class="author__subheading">{esc(para)}</h3>')
        else:
            html.append('<p>%s</p>' % esc(para).replace('\n', '<br>'))
    return mark_safe('\n\n'.join(html))
