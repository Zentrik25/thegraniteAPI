"""
throttling.py — Rate-limit classes for reader account endpoints.

Rates are defined as class attributes so config/settings.py does not need
to be modified.  All throttles key off the client IP address.
"""

from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class ReaderRegisterThrottle(SimpleRateThrottle):
    """5 registration attempts per IP per hour."""

    cache = caches["throttle"]
    scope = "reader_register"
    rate  = "5/hour"

    def get_cache_key(self, request, view) -> str:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ReaderLoginThrottle(SimpleRateThrottle):
    """10 login attempts per IP per hour."""

    cache = caches["throttle"]
    scope = "reader_login"
    rate  = "10/hour"

    def get_cache_key(self, request, view) -> str:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ReaderPasswordResetThrottle(SimpleRateThrottle):
    """3 password-reset requests per IP per hour."""

    cache = caches["throttle"]
    scope = "reader_password_reset"
    rate  = "3/hour"

    def get_cache_key(self, request, view) -> str:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ReaderVerifyEmailThrottle(SimpleRateThrottle):
    """10 verification attempts per IP per hour — separate from login."""

    cache = caches["throttle"]
    scope = "reader_verify_email"
    rate  = "10/hour"

    def get_cache_key(self, request, view) -> str:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ReaderResendVerificationThrottle(SimpleRateThrottle):
    """5 resend-verification requests per IP per hour — separate from password reset."""

    cache = caches["throttle"]
    scope = "reader_resend_verification"
    rate  = "5/hour"

    def get_cache_key(self, request, view) -> str:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
