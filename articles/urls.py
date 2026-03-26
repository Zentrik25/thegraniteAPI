"""
urls.py — URL routing for The Granite Post articles app.

Mount under /api/ in the project urls.py:

    path("api/", include("articles.urls")),

Named routes (breaking, top-stories, featured) are declared BEFORE
the <slug> catch-all so Django matches them correctly.
"""

from django.urls import path

from .views import (
    ArticleDetailView,
    ArticleListCreateView,
    BreakingNewsView,
    CategoryDetailView,
    CategoryListView,
    FeaturedArticlesView,
    TagDetailView,
    TagListView,
    TopStoryGridView,
)

app_name = "articles"

urlpatterns = [
    # ── Articles ──────────────────────────────────────────────────────
    # Specific named routes must come before the <slug> catch-all.
    path("articles/breaking/",    BreakingNewsView.as_view(),     name="article-breaking"),
    path("articles/top-stories/", TopStoryGridView.as_view(),     name="article-top-stories"),
    path("articles/featured/",    FeaturedArticlesView.as_view(), name="article-featured"),
    path("articles/",             ArticleListCreateView.as_view(), name="article-list"),
    path("articles/<slug:slug>/", ArticleDetailView.as_view(),    name="article-detail"),

    # ── Categories ────────────────────────────────────────────────────
    path("categories/",             CategoryListView.as_view(),   name="category-list"),
    path("categories/<slug:slug>/", CategoryDetailView.as_view(), name="category-detail"),

    # ── Tags ──────────────────────────────────────────────────────────
    path("tags/",             TagListView.as_view(),   name="tag-list"),
    path("tags/<slug:slug>/", TagDetailView.as_view(), name="tag-detail"),
]
