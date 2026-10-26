"""System checks (shown by runserver, migrate and `manage.py check`)."""

from django.conf import settings
from django.core.checks import Warning, register

from backend.email_config import smtp_port_problem


@register()
def smtp_port_check(app_configs, **kwargs):
    """EMAIL_PORT must fit EMAIL_USE_TLS / EMAIL_USE_SSL (only when SMTP is used)."""
    if not settings.EMAIL_HOST:
        return []
    problem = smtp_port_problem(settings.EMAIL_PORT, settings.EMAIL_USE_TLS, settings.EMAIL_USE_SSL)
    if not problem:
        return []
    return [Warning(problem, hint='465: EMAIL_USE_SSL=True, EMAIL_USE_TLS=False. '
                                  '587: EMAIL_USE_TLS=True, EMAIL_USE_SSL=False.',
                    id='api.W001')]
