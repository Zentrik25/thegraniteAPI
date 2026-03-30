"""
views.py — API views for The Granite Post articles app.

Endpoints
---------
GET  /api/articles/                — paginated feed of published articles
POST /api/articles/                — create article (staff only)
GET  /api/articles/<slug>/         — full article detail
PATCH /api/articles/<slug>/        — update article (author or staff)
DELETE /api/articles/<slug>/       — archive instead of hard delete (staff only)

GET  /api/articles/breaking/       — current breaking news feed
GET  /api/articles/top-stories/    — 6-slot top story grid (empty slots = null)
GET  /api/articles/featured/       — featured / hero articles

GET  /api/categories/              — all categories
GET  /api/categories/<slug>/       — category + its published articles

GET  /api/tags/                    — all tags
GET  /api/tags/<slug>/             — tag + its published articles
"""

from django.shortcuts import get_object_or_404
from rest_framework import filters, generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsPagination

from .models import Article, Category, Tag, TOP_STORY_MAX, TOP_STORY_MIN
from .serializers import (
    ArticleDetailSerializer,
    ArticleListSerializer,
    ArticleWriteSerializer,
    CategorySerializer,
    TagSerializer,
    TopStoryGridSerializer,
)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class IsAuthorOrStaff(permissions.BasePermission):
    """Authors may edit their own articles; editors and above may edit any article."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        # Use the project role model rather than the raw is_staff flag, which is
        # synced by signals and can diverge under bulk updates or test bypasses.
        return obj.author == request.user or request.user.can_edit_any_article


# ---------------------------------------------------------------------------
# Article views
# ---------------------------------------------------------------------------

class ArticleListCreateView(generics.ListCreateAPIView):
    """
    GET  — paginated, filterable feed of published articles.
    POST — create a new article (staff only).
    """

    pagination_class = StandardResultsPagination
    filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
    search_fields    = ["title", "excerpt", "body", "tags__name", "category__name"]
    ordering_fields  = ["published_at", "created_at", "title"]
    ordering         = ["-published_at"]

    def get_queryset(self):
        qs = Article.objects.with_related()
        # Editors and above see all statuses; everyone else sees published only.
        # Guard is_authenticated before accessing role properties — AnonymousUser
        # does not have can_edit_any_article.
        user = self.request.user
        if user.is_authenticated and user.can_edit_any_article:
            return qs.all()
        return qs.published()

    def get_serializer_class(self):
        return ArticleWriteSerializer if self.request.method == "POST" else ArticleListSerializer

    def get_permissions(self):
        return [permissions.IsAdminUser()] if self.request.method == "POST" else [permissions.AllowAny()]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class ArticleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    — full article detail by slug.
    PATCH  — partial update (author or staff).
    DELETE — archives the article instead of hard-deleting it.
    """

    lookup_field = "slug"

    def get_queryset(self):
        qs = Article.objects.with_related()
        user = self.request.user
        if user.is_authenticated and user.can_edit_any_article:
            return qs.all()
        # For write methods, return all articles so IsAuthorOrStaff can fire
        # at object-level and return 403 rather than a misleading 404.
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return qs.all()
        return qs.published()

    def get_serializer_class(self):
        return ArticleWriteSerializer if self.request.method in ("PUT", "PATCH") else ArticleDetailSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [IsAuthorOrStaff()]
        return [permissions.AllowAny()]

    def destroy(self, request, *args, **kwargs):
        """Archive instead of hard delete — preserves editorial history."""
        article = self.get_object()
        article.status = "archived"
        article.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Article archived."}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Editorial placement views
# ---------------------------------------------------------------------------

class BreakingNewsView(generics.ListAPIView):
    """GET /api/articles/breaking/ — active breaking news articles."""

    serializer_class   = ArticleListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Article.objects.breaking().with_related().order_by("-published_at")


class TopStoryGridView(APIView):
    """
    GET /api/articles/top-stories/

    Returns exactly 6 entries representing the top story grid.
    Empty slots are returned as { "rank": N, "article": null } so the
    frontend always receives a fixed-length array and can render
    placeholder cards without conditional logic.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        occupied = {
            a.top_story_rank: a
            for a in Article.objects.top_stories().with_related()
        }

        grid = []
        for rank in range(TOP_STORY_MIN, TOP_STORY_MAX + 1):
            article = occupied.get(rank)
            grid.append({
                "rank":    rank,
                "article": ArticleListSerializer(article, context={"request": request}).data
                           if article else None,
            })

        return Response(grid)


class FeaturedArticlesView(generics.ListAPIView):
    """GET /api/articles/featured/ — hero + featured articles, rank order."""

    serializer_class   = ArticleListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Article.objects.featured().with_related()


# ---------------------------------------------------------------------------
# Category views
# ---------------------------------------------------------------------------

class CategoryListView(generics.ListAPIView):
    queryset           = Category.objects.all()
    serializer_class   = CategorySerializer
    permission_classes = [permissions.AllowAny]


class CategoryDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        category = get_object_or_404(Category, slug=slug)
        articles = (
            Article.objects
            .by_category(slug)
            .with_related()
            .order_by("-published_at")
        )
        return Response({
            "category": CategorySerializer(category).data,
            "articles": ArticleListSerializer(articles, many=True, context={"request": request}).data,
        })


# ---------------------------------------------------------------------------
# Tag views
# ---------------------------------------------------------------------------

class TagListView(generics.ListAPIView):
    queryset           = Tag.objects.all()
    serializer_class   = TagSerializer
    permission_classes = [permissions.AllowAny]


class TagDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        tag = get_object_or_404(Tag, slug=slug)
        articles = (
            Article.objects
            .by_tag(slug)
            .with_related()
            .order_by("-published_at")
        )
        return Response({
            "tag":      TagSerializer(tag).data,
            "articles": ArticleListSerializer(articles, many=True, context={"request": request}).data,
        })
