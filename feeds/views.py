from django.contrib.sitemaps.views import sitemap
from django.contrib.syndication.views import Feed
from django.http import Http404
from django.utils.feedgenerator import Rss201rev2Feed

from articles.models import Article, Category

from .sitemaps import NEWS_SITEMAPS, SITEMAPS


class LatestArticlesFeed(Feed):
    """
    Main RSS 2.0 feed served at /rss/
    Returns the 50 most recently published articles across all sections.
    """

    title       = "The Granite Post"
    link        = "/"
    description = "Latest news from The Granite Post — Zimbabwe's independent digital newsroom."
    feed_type   = Rss201rev2Feed
    language    = "en"

    def items(self):
        return (
            Article.objects
            .published()
            .with_related()
            .order_by("-published_at")[:50]
        )

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt or item.title

    def item_link(self, item):
        return f"/articles/{item.slug}/"

    def item_pubdate(self, item):
        return item.published_at

    def item_updateddate(self, item):
        return item.updated_at

    def item_author_name(self, item):
        return item.author.byline

    def item_categories(self, item):
        tags = list(item.tags.values_list("name", flat=True))
        if item.category:
            tags.insert(0, item.category.name)
        return tags

    def item_enclosure_url(self, item):
        return item.image_url or None

    def item_enclosure_length(self, item):
        return 0

    def item_enclosure_mime_type(self, item):
        if not item.image_url:
            return None
        url = item.image_url.lower()
        if url.endswith(".png"):
            return "image/png"
        if url.endswith(".webp"):
            return "image/webp"
        return "image/jpeg"


class CategoryFeed(Feed):
    """
    Per-category RSS 2.0 feed served at /rss/<category-slug>/
    Returns the 50 most recently published articles in the given section.
    """

    feed_type = Rss201rev2Feed
    language  = "en"

    def get_object(self, request, category_slug):
        try:
            return Category.objects.get(slug=category_slug)
        except Category.DoesNotExist:
            raise Http404(f"No category found with slug '{category_slug}'.")

    def title(self, obj):
        return f"The Granite Post — {obj.name}"

    def link(self, obj):
        return f"/categories/{obj.slug}/"

    def description(self, obj):
        return obj.description or f"Latest {obj.name} news from The Granite Post."

    def items(self, obj):
        return (
            Article.objects
            .by_category(obj.slug)
            .with_related()
            .order_by("-published_at")[:50]
        )

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.excerpt or item.title

    def item_link(self, item):
        return f"/articles/{item.slug}/"

    def item_pubdate(self, item):
        return item.published_at

    def item_updateddate(self, item):
        return item.updated_at

    def item_author_name(self, item):
        return item.author.byline


def sitemap_view(request):
    """Standard XML sitemap — all published articles and categories."""
    return sitemap(request, SITEMAPS, content_type="application/xml")


def news_sitemap_view(request):
    """Google News XML sitemap — articles from the last 48 hours only."""
    return sitemap(request, NEWS_SITEMAPS, content_type="application/xml")
