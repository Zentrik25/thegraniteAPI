from django.urls import path

from .views import (
    CategoryFeed,
    LatestArticlesFeed,
    news_sitemap_view,
    sitemap_view,
)

app_name = "feeds"

urlpatterns = [
    # RSS feeds — no api/v1 prefix, these are public syndication URLs
    path("rss/",                      LatestArticlesFeed(), name="rss-latest"),
    path("rss/<slug:category_slug>/", CategoryFeed(),       name="rss-category"),

    # Sitemaps
    path("sitemap.xml",      sitemap_view,      name="sitemap"),
    path("news-sitemap.xml", news_sitemap_view, name="news-sitemap"),
]
