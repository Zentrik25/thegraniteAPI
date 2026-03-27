import logging

from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger("core.throttling")


class RoleBasedThrottle(SimpleRateThrottle):
    cache = caches["throttle"]

    def get_scope(self, request) -> str:
        if request.user and request.user.is_authenticated:
            return getattr(request.user, "role", "author")
        return "anon"

    def get_cache_key(self, request, view) -> str:
        scope = self.get_scope(request)
        ident = (
            f"u{request.user.pk}"
            if request.user and request.user.is_authenticated
            else self.get_ident(request)
        )
        return self.cache_format % {"scope": scope, "ident": ident}

    def get_rate(self) -> str:
        from django.conf import settings
        rates = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
        scope = getattr(self, "_resolved_scope", "anon")
        return rates.get(scope, "200/hour")

    def allow_request(self, request, view) -> bool:
        self._resolved_scope     = self.get_scope(request)
        self.scope               = self._resolved_scope
        self.rate                = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                "Rate limit exceeded: scope=%s path=%s",
                self._resolved_scope,
                request.path,
            )

        return allowed


class BurstRateThrottle(SimpleRateThrottle):
    cache = caches["throttle"]

    BURST_RATES = {
        "anon":          "5/min",
        "contributor":   "20/min",
        "author":        "20/min",
        "editor":        "40/min",
        "senior_editor": "60/min",
        "admin":         "120/min",
    }

    def get_scope(self, request) -> str:
        if request.user and request.user.is_authenticated:
            return getattr(request.user, "role", "author")
        return "anon"

    def get_cache_key(self, request, view) -> str:
        scope = self.get_scope(request)
        ident = (
            f"u{request.user.pk}"
            if request.user and request.user.is_authenticated
            else self.get_ident(request)
        )
        return self.cache_format % {"scope": f"burst_{scope}", "ident": ident}

    def get_rate(self) -> str:
        scope = getattr(self, "_resolved_scope", "anon")
        return self.BURST_RATES.get(scope, "5/min")

    def allow_request(self, request, view) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        self._resolved_scope     = self.get_scope(request)
        self.scope               = f"burst_{self._resolved_scope}"
        self.rate                = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


class StrictAnonThrottle(SimpleRateThrottle):
    cache = caches["throttle"]
    scope = "strict_anon"
    rate  = "10/hour"

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
