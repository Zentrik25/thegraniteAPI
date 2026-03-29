"""
middleware.py — Paywall middleware for The Granite Post.

PaywallMiddleware intercepts GET requests to /api/v1/articles/<slug>/ and
checks whether the article is premium-gated. If it is, the reader must have
an active paid subscription (Premium or Supporter plan).

Access rules:
  - Non-premium articles (is_premium=False): pass through immediately.
  - Staff users (StaffUser JWT): always pass through regardless of subscription.
  - Unauthenticated requests to premium articles: 402 Payment Required.
  - Authenticated readers with FREE_ONLY plan: 402 Payment Required.
  - Authenticated readers with PREMIUM or ALL plan: pass through.

Subscription status is cached per reader for 5 minutes to avoid a DB hit
on every article request.
"""

import logging
import re
from typing import Callable

from django.core.cache import cache
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger("subscriptions.middleware")

# Pattern matches /api/v1/articles/<slug>/
_ARTICLE_DETAIL_RE = re.compile(r"^/api/v1/articles/(?P<slug>[^/]+)/?$")

# Cache TTL for subscription status per reader (seconds)
_CACHE_TTL = 300


class PaywallMiddleware:
    """
    Middleware that enforces premium article access based on subscription plan.

    Only intercepts GET requests matching /api/v1/articles/<slug>/.
    All other methods and paths are passed through immediately.

    Subscription status is cached per reader for 5 minutes.
    Staff users (identified by a valid staff JWT) always bypass the paywall.
    """

    def __init__(self, get_response: Callable) -> None:
        """Store the next middleware/view callable."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        """Process the request, enforcing the paywall where applicable."""
        # Only intercept GET requests that match the article detail path
        if request.method != "GET":
            return self.get_response(request)

        match = _ARTICLE_DETAIL_RE.match(request.path_info)
        if not match:
            return self.get_response(request)

        slug = match.group("slug")

        # Fetch the article — lazy import to avoid circular dependency at startup
        from articles.models import Article, PublishStatus

        try:
            article = Article.objects.only("slug", "is_premium", "status").get(
                slug=slug,
                status=PublishStatus.PUBLISHED,
            )
        except Article.DoesNotExist:
            # Let the view return the 404 — not our concern
            return self.get_response(request)

        # Non-premium articles: pass through immediately
        if not article.is_premium:
            return self.get_response(request)

        # Premium article — check authentication
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return self._paywall_response(slug)

        raw_token = auth_header.split(" ", 1)[1]

        # Check if this is a staff JWT (bypasses paywall entirely)
        if _is_staff_token(raw_token):
            return self.get_response(request)

        # Check if this is a reader JWT with a qualifying subscription
        reader_id = _get_reader_id_from_token(raw_token)
        if not reader_id:
            return self._paywall_response(slug)

        if _reader_has_premium_access(reader_id):
            return self.get_response(request)

        return self._paywall_response(slug)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _paywall_response(self, slug: str) -> JsonResponse:
        """Return a 402 Payment Required response with upgrade information."""
        from subscriptions.models import ArticleAccess, SubscriptionPlan

        plans = list(
            SubscriptionPlan.objects.filter(
                is_active=True,
                article_access__in=[ArticleAccess.PREMIUM, ArticleAccess.ALL],
            )
            .order_by("price_usd")
            .values("name", "slug", "price_usd", "billing_period")
        )

        upgrade_plans = [
            {
                "name":            p["name"],
                "slug":            p["slug"],
                "price_usd":       str(p["price_usd"]),
                "billing_period":  p["billing_period"],
                "currency":        "USD",
            }
            for p in plans
        ]

        return JsonResponse(
            {
                "detail": "This article is for premium subscribers only.",
                "code":   "premium_required",
                "upgrade_url": "/subscription/upgrade/",
                "upgrade_plans": upgrade_plans,
            },
            status=402,
        )


# ---------------------------------------------------------------------------
# Token helpers (module-level, not bound to the class)
# ---------------------------------------------------------------------------

def _is_staff_token(raw_token: str) -> bool:
    """
    Return True if *raw_token* is a valid staff access token (token_type='access').

    Validates the token using SimpleJWT without hitting the database.
    Returns False on any error.
    """
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken(raw_token)
        # Staff tokens have token_type == "access"
        return token.get("token_type") == "access"
    except Exception:  # noqa: BLE001
        return False


def _get_reader_id_from_token(raw_token: str) -> str | None:
    """
    Extract the reader_id claim from a reader access token.

    Returns None if the token is invalid, expired, or not a reader token.
    """
    try:
        from accounts.authentication import ReaderAccessToken
        token = ReaderAccessToken(raw_token)
        return token.get("reader_id")
    except Exception:  # noqa: BLE001
        return None


def _reader_has_premium_access(reader_id: str) -> bool:
    """
    Return True if the reader holds an active subscription with PREMIUM or ALL access.

    Results are cached per reader for _CACHE_TTL seconds to avoid DB overhead
    on every article request.
    """
    cache_key = f"subscriptions:reader:{reader_id}:status"
    cached    = cache.get(cache_key)

    if cached is not None:
        return cached

    from subscriptions.models import ArticleAccess, Subscription, SubscriptionStatus
    from datetime import date

    today = date.today()
    has_access = Subscription.objects.filter(
        reader_id=reader_id,
        status=SubscriptionStatus.ACTIVE,
        current_period_end__gte=today,
        plan__article_access__in=[ArticleAccess.PREMIUM, ArticleAccess.ALL],
        plan__is_active=True,
    ).exists()

    cache.set(cache_key, has_access, _CACHE_TTL)
    return has_access
