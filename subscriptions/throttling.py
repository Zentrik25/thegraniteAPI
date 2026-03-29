"""
Endpoint-specific throttles for sensitive subscription payment flows.
"""

from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class PaymentPollThrottle(SimpleRateThrottle):
    """
    Limit reader payment polling per payment so one browser cannot hammer
    the upstream provider indefinitely.
    """

    cache = caches["throttle"]
    rate = "30/min"
    scope = "payment_poll"

    def get_cache_key(self, request, view) -> str:
        payment_id = getattr(view, "kwargs", {}).get("payment_id", "unknown")
        ident = (
            f"u{request.user.pk}"
            if request.user and request.user.is_authenticated
            else self.get_ident(request)
        )
        return self.cache_format % {
            "scope": f"{self.scope}:{payment_id}",
            "ident": ident,
        }


class PaynowCallbackThrottle(SimpleRateThrottle):
    """
    Apply a long-window cap to unauthenticated Paynow callbacks per source IP.
    """

    cache = caches["throttle"]
    rate = "300/hour"
    scope = "paynow_callback"

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
