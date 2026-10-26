"""
SMTP port vs. encryption: 465 is SSL from the first byte (EMAIL_USE_SSL), 587
upgrades a plain connection with STARTTLS (EMAIL_USE_TLS). The wrong pair hangs
or fails at connect time, so it is reported before any email is sent: for now
as a system check warning (api/checks.py).
"""

# Port -> the (EMAIL_USE_TLS, EMAIL_USE_SSL) pair it needs.
_REQUIRED = {
    465: (False, True),
    587: (True, False),
}


def smtp_port_problem(port, use_tls, use_ssl):
    """'' if the port and the TLS/SSL flags fit together, else what is wrong.
    Other ports (25, 2525...) are not checked, except for both flags on."""
    if use_tls and use_ssl:
        return 'EMAIL_USE_TLS and EMAIL_USE_SSL are both on; set only one of them.'
    required = _REQUIRED.get(port)
    if required and (bool(use_tls), bool(use_ssl)) != required:
        tls, ssl = required
        return (f'EMAIL_PORT={port} needs EMAIL_USE_TLS={tls} and EMAIL_USE_SSL={ssl} '
                f'(now EMAIL_USE_TLS={bool(use_tls)}, EMAIL_USE_SSL={bool(use_ssl)}).')
    return ''
