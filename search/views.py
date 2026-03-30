import logging

from django.contrib.postgres.search import (
    SearchHeadline,
    SearchQuery,
    SearchRank,
    SearchVector,
)
from django.db.models import F
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import Article
from articles.serializers import ArticleListSerializer
from core.cache import get_or_set_cache
from core.pagination import StandardResultsPagination

logger = logging.getLogger("search.views")

# Minimum query length — prevents single-character searches
# that would return too many results to be useful.
MIN_QUERY_LENGTH = 2

# Maximum query length — prevents extremely long queries that
# could be used to attack the search endpoint.
MAX_QUERY_LENGTH = 200

# Search result cache TTL in seconds.
SEARCH_CACHE_TTL = 120


class ArticleSearchView(APIView):
    """
    GET /api/v1/search/?q=<query>

    Full-text search across published articles using PostgreSQL's
    built-in search engine.

    Query parameters
    ----------------
    q        — search query (required, 2-200 characters)
    page     — page number (default: 1)
    page_size — results per page (default: 20, max: 50)

    Ranking
    -------
    Results are ranked by relevance using PostgreSQL ts_rank_cd:
      - Title matches rank highest    (weight A)
      - Excerpt matches rank second   (weight B)
      - Body matches rank third       (weight C)

    A search for "harare floods" will rank articles with "harare floods"
    in the title above articles that only mention it in the body.

    Highlights
    ----------
    Each result includes a headline field — the most relevant sentence
    from the article body with the matching terms wrapped in <mark> tags.
    The frontend renders this as the search result snippet.

    Caching
    -------
    Results are cached for 2 minutes per unique query + page combination.
    A cache miss hits PostgreSQL's GIN index which is extremely fast
    (sub-10ms on thousands of articles).

    Examples
    --------
    GET /api/v1/search/?q=harare+floods
    GET /api/v1/search/?q=zimbabwe+economy&page=2
    GET /api/v1/search/?q=mnangagwa&page_size=10
    """

    permission_classes = [AllowAny]
    throttle_classes   = []

    def get(self, request):
        query     = request.query_params.get("q", "").strip()
        page      = request.query_params.get("page", 1)
        page_size = min(
            int(request.query_params.get("page_size", 20)),
            50,
        )

        # Validate query length.
        if len(query) < MIN_QUERY_LENGTH:
            return Response({
                "status":  "error",
                "code":    "query_too_short",
                "message": f"Search query must be at least {MIN_QUERY_LENGTH} characters.",
                "query":   query,
            }, status=400)

        if len(query) > MAX_QUERY_LENGTH:
            return Response({
                "status":  "error",
                "code":    "query_too_long",
                "message": f"Search query must be {MAX_QUERY_LENGTH} characters or fewer.",
                "query":   query,
            }, status=400)

        cache_key = f"search:{query.lower()}:page{page}:size{page_size}"

        def compute():
            return self._execute_search(query, int(page), page_size, request)

        result = get_or_set_cache(cache_key, compute, ttl=SEARCH_CACHE_TTL)
        return Response(result)

    def _execute_search(
        self,
        query: str,
        page: int,
        page_size: int,
        request,
    ) -> dict:
        """
        Execute the full-text search against PostgreSQL.

        Strategy
        --------
        1. Use the pre-computed search_vector field on Article for fast
           GIN index lookups. This avoids recomputing the vector on
           every query.
        2. Fall back to a live SearchVector computation if search_vector
           is null (article was saved before the search app was installed).
        3. Annotate with ts_rank_cd for relevance scoring.
        4. Annotate with SearchHeadline for result snippets.
        5. Paginate and serialise.
        """
        search_query = SearchQuery(query, config="english", search_type="websearch")

        # Rank weights: D=0.1, C=0.2, B=0.4, A=1.0
        # These amplify title matches over body matches.
        rank_weights = [0.1, 0.2, 0.4, 1.0]

        articles = (
            Article.objects
            .published()
            .with_related()
            .filter(search_vector=search_query)
            .annotate(
                rank=SearchRank(
                    F("search_vector"),
                    search_query,
                    weights=rank_weights,
                    cover_density=True,
                ),
                headline=SearchHeadline(
                    "body",
                    search_query,
                    config="english",
                    start_sel="<mark>",
                    stop_sel="</mark>",
                    max_words=50,
                    min_words=25,
                    max_fragments=2,
                ),
            )
            .order_by("-rank", "-published_at")
        )

        # Fallback: if search_vector is not populated yet, use a live vector.
        # This handles articles saved before the search app was installed.
        if not articles.exists():
            live_vector = (
                SearchVector("title",   weight="A", config="english") +
                SearchVector("excerpt", weight="B", config="english") +
                SearchVector("body",    weight="C", config="english")
            )
            articles = (
                Article.objects
                .published()
                .with_related()
                .annotate(
                    live_vector=live_vector,
                    rank=SearchRank(
                        live_vector,
                        search_query,
                        weights=rank_weights,
                        cover_density=True,
                    ),
                    headline=SearchHeadline(
                        "body",
                        search_query,
                        config="english",
                        start_sel="<mark>",
                        stop_sel="</mark>",
                        max_words=50,
                        min_words=25,
                        max_fragments=2,
                    ),
                )
                .filter(live_vector=search_query)
                .order_by("-rank", "-published_at")
            )

        total_count = articles.count()
        import math
        total_pages  = max(1, math.ceil(total_count / page_size))
        current_page = max(1, min(page, total_pages))
        offset       = (current_page - 1) * page_size
        page_articles = articles[offset: offset + page_size]

        # Build next / previous links.
        base_url = request.build_absolute_uri(
            f"/api/v1/search/?q={query}&page_size={page_size}&page="
        )
        next_link     = f"{base_url}{current_page + 1}" if current_page < total_pages else None
        previous_link = f"{base_url}{current_page - 1}" if current_page > 1 else None

        # Serialise results.
        results = []
        for article in page_articles:
            article_data = ArticleListSerializer(
                article, context={"request": request}
            ).data
            # SearchHeadline is derived directly from the body field.
            # For premium articles the body is gated content — returning
            # a body-derived snippet would leak it regardless of the
            # serializer's field exclusions.  Use the article's public
            # excerpt instead.  Free articles get the normal body snippet.
            headline = (
                article.excerpt or ""
                if article.is_premium
                else getattr(article, "headline", "")
            )
            results.append({
                "rank":     round(float(article.rank), 4),
                "headline": headline,
                "article":  article_data,
            })

        logger.info(
            "Search: query='%s' results=%d page=%d",
            query,
            total_count,
            current_page,
        )

        return {
            "status":       "ok",
            "query":        query,
            "count":        total_count,
            "total_pages":  total_pages,
            "current_page": current_page,
            "next":         next_link,
            "previous":     previous_link,
            "results":      results,
        }
