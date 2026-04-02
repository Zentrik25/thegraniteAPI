import logging
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import Article
from core.cache import get_or_set_cache
from core.middleware import _get_client_ip
from core.throttling import BurstRateThrottle
from users.permissions import IsEditorOrAbove

from .models import ArticleView
from .serializers import TrendingArticleSerializer, ViewRecordedSerializer

logger = logging.getLogger("analytics.views")

# Supported trending periods and their hour windows.
PERIOD_HOURS = {
    "day":   24,
    "week":  168,
}


class RecordViewView(APIView):
    """
    POST /api/v1/analytics/articles/<slug>/view/

    Records one view per IP address per article per calendar day.
    Returns whether this specific request was counted or was a duplicate.

    Staff views are never counted — editors reading their own articles
    should not inflate reader-facing view counts.
    """

    permission_classes = [AllowAny]
    throttle_classes   = [BurstRateThrottle]

    def post(self, request, slug):
        article = get_object_or_404(
            Article.objects.published().only("id", "slug", "view_count"),
            slug=slug,
        )

        # Do not count staff views.
        if request.user.is_authenticated and request.user.is_staff:
            return Response(
                ViewRecordedSerializer({
                    "article_slug": slug,
                    "view_count":   article.view_count,
                    "recorded":     False,
                }).data
            )

        ip           = _get_client_ip(request)
        ip_hash      = ArticleView.hash_ip(ip)
        session_hash = ArticleView.hash_session(
            getattr(request.session, "session_key", None) or ""
        )
        today = timezone.now().date()

        recorded = False
        try:
            with transaction.atomic():
                ArticleView.objects.create(
                    article      = article,
                    ip_hash      = ip_hash,
                    session_hash = session_hash,
                    viewed_at    = timezone.now(),
                    viewed_date  = today,
                )
            recorded = True
            logger.debug(
                "View recorded: slug=%s ip_hash=%s...",
                slug,
                ip_hash[:8],
            )
        except IntegrityError:
            # UniqueConstraint violation — already counted today from this IP.
            # The savepoint is rolled back; the outer transaction stays healthy.
            pass

        # Refresh view_count from DB after the signal has incremented it.
        article.refresh_from_db(fields=["view_count"])

        return Response(
            ViewRecordedSerializer({
                "article_slug": slug,
                "view_count":   article.view_count,
                "recorded":     recorded,
            }).data
        )


class TrendingArticlesView(APIView):
    """
    GET /api/v1/analytics/trending/?period=day|week

    Returns the top 10 most viewed articles in the requested time window.
    Results are cached for 5 minutes — the trending query aggregates
    potentially thousands of ArticleView rows on every call without caching.

    period=day  — last 24 hours  (default)
    period=week — last 7 days
    """

    permission_classes = [AllowAny]
    throttle_classes   = []

    def get(self, request):
        period = request.query_params.get("period", "day")
        if period not in PERIOD_HOURS:
            period = "day"

        cache_key = f"analytics:trending:{period}"

        def compute():
            from django.db.models import Count
            from articles.serializers import ArticleListSerializer

            hours  = PERIOD_HOURS[period]
            cutoff = timezone.now() - timedelta(hours=hours)

            # Aggregate view counts per article in the time window.
            top_rows = (
                ArticleView.objects
                .filter(viewed_at__gte=cutoff)
                .values("article_id")
                .annotate(count=Count("id"))
                .order_by("-count")[:10]
            )

            if not top_rows:
                return []

            article_counts = {row["article_id"]: row["count"] for row in top_rows}

            # Fetch the article objects for the top IDs in one query.
            articles = (
                Article.objects
                .published()
                .filter(pk__in=article_counts.keys())
                .with_related()
            )
            article_map = {a.pk: a for a in articles}

            results = []
            for rank, (article_id, count) in enumerate(
                sorted(article_counts.items(), key=lambda x: -x[1]),
                start=1,
            ):
                article = article_map.get(article_id)
                if article:
                    results.append({
                        "rank":       rank,
                        "view_count": count,
                        "article":    ArticleListSerializer(article).data,
                    })

            return results

        data = get_or_set_cache(cache_key, compute, ttl=300)
        return Response(data)


def _parse_date(value: str | None, default: date) -> date:
    """Parse a YYYY-MM-DD string, returning *default* on any error."""
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return default


class ArticleViewStatsView(APIView):
    """
    GET /api/v1/analytics/articles/<slug>/stats/

    Returns per-day view counts for an article within a date range.
    Intended for editorial dashboards — Editors and above only.

    Query params:
      from_date  YYYY-MM-DD  Start of range (default: 30 days ago).
      to_date    YYYY-MM-DD  End of range   (default: today).

    Response:
      {
        "article":     "<slug>",
        "from_date":   "YYYY-MM-DD",
        "to_date":     "YYYY-MM-DD",
        "total_views": <int>,       # all-time view_count from Article
        "daily": [
          {"date": "YYYY-MM-DD", "views": <int>},
          ...                       # only days with ≥1 view are included
        ]
      }
    """

    permission_classes = [IsAuthenticated, IsEditorOrAbove]

    def get(self, request, slug):
        article = get_object_or_404(Article, slug=slug)

        today        = timezone.now().date()
        default_from = today - timedelta(days=29)

        from_date = _parse_date(request.query_params.get("from_date"), default_from)
        to_date   = _parse_date(request.query_params.get("to_date"),   today)

        # Swap silently if caller passes them backwards.
        if from_date > to_date:
            from_date, to_date = to_date, from_date

        from django.db.models import Count

        daily_rows = (
            ArticleView.objects
            .filter(article=article, viewed_date__range=(from_date, to_date))
            .values("viewed_date")
            .annotate(views=Count("id"))
            .order_by("viewed_date")
        )

        return Response({
            "article":     slug,
            "from_date":   from_date,
            "to_date":     to_date,
            "total_views": article.view_count,
            "daily": [
                {"date": row["viewed_date"], "views": row["views"]}
                for row in daily_rows
            ],
        })
