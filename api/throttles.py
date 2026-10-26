"""
Rate limits for the public auth endpoints that send email (rates in
settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']). Counters live in the default
cache, so they are per process.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle

from .email_confirmation import normalize_email


class ClientIPThrottle(SimpleRateThrottle):
    """Per client IP, signed in or not (REMOTE_ADDR, see NUM_PROXIES in settings)."""

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class RegisterThrottle(ClientIPThrottle):
    scope = 'register'


class ResendConfirmationThrottle(ClientIPThrottle):
    scope = 'resend_confirmation'


class ResendConfirmationEmailThrottle(SimpleRateThrottle):
    """Per address, whichever IP asks; the address is hashed in the cache key."""
    scope = 'resend_confirmation_email'

    def get_cache_key(self, request, view):
        email = normalize_email(request.data.get('email'))
        if not email:
            return None  # nothing to send to: the view answers 400
        ident = hashlib.sha256(email.encode()).hexdigest()
        return self.cache_format % {'scope': self.scope, 'ident': ident}
