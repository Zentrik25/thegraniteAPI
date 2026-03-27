from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class CommentRateThrottle(SimpleRateThrottle):
    """
    Strict per-IP throttle for comment submission.
    Allows 3 comments per hour per IP address.
    Stored in the dedicated throttle Redis cache.
    """

    cache  = caches["throttle"]
    scope  = "comment_submit"
    rate   = "3/hour"

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
