from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class SubscribeRateThrottle(SimpleRateThrottle):
    """
    5 subscribe attempts per IP per hour.
    Prevents bots from flooding the subscriber list with fake emails.
    """

    cache  = caches["throttle"]
    scope  = "newsletter_subscribe"
    rate   = "5/hour"

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
