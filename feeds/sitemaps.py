from datetime import timedelta

from django.contrib.sitemaps import Sitemap
from django.utils import timezone

from articles.models import Article, Category


class ArticleSitemap(Sitemap):
    """
    Standard sitemap — all published articles.
    Submitted to Google Search Console and Bing Webmaster Tools.
    """

    changefreq = "daily"
    priority   = 0.8
    protocol   = "https"

    def items(self):
        return Article.objects.published().order_by("-published_at")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return f"/articles/{obj.slug}/"


class CategorySitemap(Sitemap):
    """Section landing pages included in the sitemap."""

    changefreq = "weekly"
    priority   = 0.6
    protocol   = "https"

    def items(self):
        return Category.objects.all().order_by("name")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return f"/category/{obj.slug}/"


class GoogleNewsSitemap(Sitemap):
    """
    Google News sitemap — articles published in the last 48 hours only.

    Google News will not index articles older than 48 hours from this feed
    regardless of whether you include them. Including older articles wastes
    crawl budget and may cause the sitemap to be flagged as invalid.
    """

    changefreq = "hourly"
    priority   = 1.0
    protocol   = "https"

    def items(self):
        cutoff = timezone.now() - timedelta(hours=48)
        return (
            Article.objects
            .published()
            .filter(published_at__gte=cutoff)
            .order_by("-published_at")
        )

    def lastmod(self, obj):
        return obj.published_at

    def location(self, obj):
        return f"/articles/{obj.slug}/"


# Registered sitemap dictionaries used by Django's sitemap view.
SITEMAPS = {
    "articles":   ArticleSitemap,
    "categories": CategorySitemap,
}

NEWS_SITEMAPS = {
    "news": GoogleNewsSitemap,
}
