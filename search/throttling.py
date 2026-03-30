from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class SearchRateThrottle(SimpleRateThrottle):
    """
    Rate-limit public search traffic so one client cannot hammer PostgreSQL.
    """

    cache = caches["throttle"]
    scope = "search"
    rate = "30/min"

    def get_cache_key(self, request, view) -> str:
        ident = (
            f"u{request.user.pk}"
            if request.user and request.user.is_authenticated
            else self.get_ident(request)
        )
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
