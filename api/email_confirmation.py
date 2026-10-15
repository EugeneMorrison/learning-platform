"""
Email confirmation for public sign-up.

The link carries a signed, timestamped token (django.core.signing, salted for
this purpose only): the user's id and the address it was sent to. It needs no
session or cookie, so it works in any browser. It is valid for
settings.EMAIL_CONFIRMATION_MAX_AGE and only once: after the first use the
account is confirmed and the same link reports "used". A link sent to an
address the account no longer has is rejected.

Emails are plain text plus simple HTML, in the request's language (RU/EN), from
settings.DEFAULT_FROM_EMAIL; links start with settings.SITE_URL.
"""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext, gettext_noop

logger = logging.getLogger(__name__)

SALT = 'api.email-confirmation'

# Results of confirm_email(); the login page shows a message for each.
CONFIRMED, EXPIRED, INVALID, USED = 'ok', 'expired', 'invalid', 'used'


def normalize_email(value):
    """Addresses are stored and compared lowercased."""
    return str(value or '').strip().lower()


def safe_next(value):
    """A local path to continue to after login (e.g. /enroll/<id>/), else ''.
    Kept out of the signed token: the login page checks it again anyway."""
    value = str(value or '')
    local = value.startswith('/') and not value.startswith('//') and '\\' not in value
    if local and url_has_allowed_host_and_scheme(value, allowed_hosts=None):
        return value
    return ''


def make_token(user):
    return signing.dumps({'u': user.pk, 'e': user.email}, salt=SALT, compress=True)


def confirm_email(token):
    """Confirm the account the token was issued for. Returns CONFIRMED, EXPIRED,
    INVALID (tampered, unknown user, address changed) or USED."""
    try:
        data = signing.loads(token or '', salt=SALT, max_age=settings.EMAIL_CONFIRMATION_MAX_AGE)
    except signing.SignatureExpired:
        return EXPIRED
    except signing.BadSignature:
        return INVALID
    User = get_user_model()
    user = User.objects.filter(pk=data.get('u')).first()
    if user is None or normalize_email(user.email) != normalize_email(data.get('e')):
        return INVALID
    # Single use: only the first request flips the flag.
    updated = User.objects.filter(pk=user.pk, email_verified=False).update(email_verified=True)
    return CONFIRMED if updated else USED


def _send(to, subject, template, context, language):
    """Render emails/<template>.txt and .html in `language` and send them. A
    failure is logged, not raised: the account exists either way, and the user
    can ask for the email again from the login page."""
    with translation.override(language):
        context = {**context, 'site_url': settings.SITE_URL, 'language': language}
        text = render_to_string(f'emails/{template}.txt', context)
        html = render_to_string(f'emails/{template}.html', context)
        message = EmailMultiAlternatives(gettext(subject), text, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(html, 'text/html')
    try:
        message.send()
        return True
    except Exception:  # SMTP down, refused, timed out...
        logger.exception('Could not send the "%s" email', template)
        return False


def send_confirmation_email(user, language, next_path=''):
    """`next_path` (see safe_next) rides along in the link, so the login page
    after confirming continues where sign-up started (e.g. a course to join)."""
    query = {'token': make_token(user)}
    if safe_next(next_path):
        query['next'] = safe_next(next_path)
    link = f"{settings.SITE_URL}/api/auth/confirm-email/?{urlencode(query)}"
    return _send(user.email, gettext_noop('Подтвердите адрес почты'), 'confirm_email',
                 {'username': user.username, 'link': link}, language)


def send_account_exists_email(user, language):
    """Sign-up with an address that already has an account: the response looks
    like a normal sign-up; the owner of the address learns they can log in."""
    return _send(user.email, gettext_noop('У вас уже есть аккаунт'), 'account_exists',
                 {'username': user.username, 'login_link': f'{settings.SITE_URL}/login/'}, language)
