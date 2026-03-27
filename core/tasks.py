import logging
import urllib.error
import urllib.request

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("core.tasks")


@shared_task(
    bind=True,
    queue="fast",
    max_retries=5,
    default_retry_delay=2,
    ignore_result=True,
    name="core.tasks.invalidate_article_cache",
)
def invalidate_article_cache(self, slug: str) -> None:
    try:
        from core.cache import make_cache_key

        CACHE_KEYS = settings.CACHE_KEYS
        keys = [
            CACHE_KEYS["ARTICLE_DETAIL"].format(slug=slug),
            f"view:/api/v1/articles/{slug}/",
            CACHE_KEYS["TOP_STORIES"],
            CACHE_KEYS["BREAKING_NEWS"],
            CACHE_KEYS["FEATURED"],
            "view:/api/v1/articles/top-stories/",
            "view:/api/v1/articles/breaking/",
            "view:/api/v1/articles/featured/",
            "view:/api/v1/articles/",
        ]
        cache.delete_many([make_cache_key(k) for k in keys])
        logger.info("Cache invalidated: article slug=%s (%d keys).", slug, len(keys))

    except Exception as exc:
        logger.error("Cache invalidation failed for slug=%s: %s", slug, exc)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    queue="fast",
    max_retries=3,
    default_retry_delay=5,
    ignore_result=True,
    name="core.tasks.invalidate_category_cache",
)
def invalidate_category_cache(self, category_slug: str) -> None:
    try:
        from core.cache import make_cache_key

        CACHE_KEYS = settings.CACHE_KEYS
        keys = [
            CACHE_KEYS["CATEGORY_LIST"],
            "view:/api/v1/categories/",
            f"view:/api/v1/categories/{category_slug}/",
        ]
        cache.delete_many([make_cache_key(k) for k in keys])
        logger.info("Cache invalidated: category slug=%s.", category_slug)

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(
    queue="fast",
    ignore_result=True,
    name="core.tasks.warm_top_stories_cache",
)
def warm_top_stories_cache() -> None:
    try:
        from articles.models import Article, TOP_STORY_MAX, TOP_STORY_MIN
        from articles.serializers import ArticleListSerializer
        from core.cache import make_cache_key

        articles = list(Article.objects.top_stories().with_related())
        occupied = {a.top_story_rank: a for a in articles}

        grid = [
            {
                "rank":    rank,
                "article": ArticleListSerializer(occupied[rank]).data if rank in occupied else None,
            }
            for rank in range(TOP_STORY_MIN, TOP_STORY_MAX + 1)
        ]

        cache.set(
            make_cache_key(settings.CACHE_KEYS["TOP_STORIES"]),
            grid,
            timeout=settings.CACHE_TTL["TOP_STORIES"],
        )
        logger.debug("Top stories cache warmed: %d slots.", len(grid))

    except Exception as exc:
        logger.error("Failed to warm top stories cache: %s", exc)


@shared_task(
    queue="fast",
    ignore_result=True,
    name="core.tasks.warm_breaking_cache",
)
def warm_breaking_cache() -> None:
    try:
        from articles.models import Article
        from articles.serializers import ArticleListSerializer
        from core.cache import make_cache_key

        articles = list(
            Article.objects.breaking().with_related().order_by("-published_at")[:10]
        )
        data = ArticleListSerializer(articles, many=True).data

        cache.set(
            make_cache_key(settings.CACHE_KEYS["BREAKING_NEWS"]),
            data,
            timeout=settings.CACHE_TTL["BREAKING_NEWS"],
        )
        logger.debug("Breaking news cache warmed: %d articles.", len(articles))

    except Exception as exc:
        logger.error("Failed to warm breaking news cache: %s", exc)


@shared_task(
    queue="fast",
    ignore_result=True,
    name="core.tasks.warm_featured_cache",
)
def warm_featured_cache() -> None:
    try:
        from articles.models import Article
        from articles.serializers import ArticleListSerializer
        from core.cache import make_cache_key

        articles = list(Article.objects.featured().with_related())
        data     = ArticleListSerializer(articles, many=True).data

        cache.set(
            make_cache_key(settings.CACHE_KEYS["FEATURED"]),
            data,
            timeout=settings.CACHE_TTL["FEATURED"],
        )
        logger.debug("Featured cache warmed: %d articles.", len(articles))

    except Exception as exc:
        logger.error("Failed to warm featured cache: %s", exc)


@shared_task(
    bind=True,
    queue="slow",
    max_retries=3,
    default_retry_delay=120,
    ignore_result=True,
    name="core.tasks.ping_sitemaps",
)
def ping_sitemaps(self) -> None:
    sitemap_url = "https://thegranite.co.zw/sitemap.xml"
    endpoints   = [
        f"https://www.google.com/ping?sitemap={sitemap_url}",
        f"https://www.bing.com/ping?sitemap={sitemap_url}",
    ]
    errors = []
    for url in endpoints:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                logger.info("Sitemap pinged: %s → HTTP %d.", url, resp.status)
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("Sitemap ping failed for %s: %s", url, exc)
            errors.append(str(exc))

    if errors and self.request.retries < self.max_retries:
        raise self.retry(exc=Exception("; ".join(errors)))


@shared_task(
    bind=True,
    queue="slow",
    max_retries=2,
    default_retry_delay=300,
    ignore_result=True,
    name="core.tasks.process_image",
)
def process_image(self, media_id: int) -> None:
    logger.info("process_image queued: media_id=%d (pending media app).", media_id)
