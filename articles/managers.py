"""
managers.py — Custom QuerySet and Manager for Article.

All public-facing filter logic lives here so views stay clean.
Every method is chainable. Call .with_related() on any queryset
that iterates articles to avoid N+1 queries.
"""

from django.db import models
from django.utils import timezone

from .models import TOP_STORY_MAX, TOP_STORY_MIN


class ArticleQuerySet(models.QuerySet):

    # ------------------------------------------------------------------
    # Status filters
    # ------------------------------------------------------------------

    def published(self):
        """Live articles only — status=published and published_at in the past."""
        return self.filter(
            status="published",
            published_at__lte=timezone.now(),
        )

    def drafts(self):
        return self.filter(status="draft")

    def in_review(self):
        return self.filter(status="review")

    def archived(self):
        return self.filter(status="archived")

    # ------------------------------------------------------------------
    # Editorial placement
    # ------------------------------------------------------------------

    def breaking(self):
        """Published articles currently flagged as breaking news."""
        return self.published().filter(is_breaking=True)

    def top_stories(self):
        """
        All published top story articles ordered by rank (1 = lead).
        Returns up to 6 articles — one per slot.
        """
        return (
            self.published()
            .filter(top_story_rank__isnull=False)
            .order_by("top_story_rank")
        )

    def top_story_at_rank(self, rank: int):
        """Return the article at a specific top story rank, or None."""
        if not (TOP_STORY_MIN <= rank <= TOP_STORY_MAX):
            raise ValueError(f"top_story rank must be {TOP_STORY_MIN}–{TOP_STORY_MAX}, got {rank}.")
        return self.published().filter(top_story_rank=rank).first()

    def featured(self):
        """Published articles with a featured_rank, ordered hero-first."""
        return self.published().filter(featured_rank__isnull=False).order_by("featured_rank")

    # ------------------------------------------------------------------
    # Taxonomy filters
    # ------------------------------------------------------------------

    def by_category(self, slug: str):
        return self.published().filter(category__slug=slug)

    def by_tag(self, slug: str):
        return self.published().filter(tags__slug=slug)

    def by_author(self, user):
        return self.filter(author=user)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def recent(self, n: int = 10):
        """Most recently published articles."""
        return self.published().order_by("-published_at")[:n]

    def with_related(self):
        """
        Eagerly load FK and M2M relations.
        Call on any queryset that will iterate over articles in a template or
        serializer to prevent N+1 query hits on author, category, and tags.
        """
        return self.select_related("author", "category").prefetch_related("tags")


class ArticleManager(models.Manager):
    """Default manager — wraps ArticleQuerySet for full chain support."""

    def get_queryset(self) -> ArticleQuerySet:
        return ArticleQuerySet(self.model, using=self._db)

    # Pass-throughs so callers can write Article.objects.published() etc.

    def published(self):
        return self.get_queryset().published()

    def breaking(self):
        return self.get_queryset().breaking()

    def top_stories(self):
        return self.get_queryset().top_stories()

    def top_story_at_rank(self, rank: int):
        return self.get_queryset().top_story_at_rank(rank)

    def featured(self):
        return self.get_queryset().featured()

    def recent(self, n: int = 10):
        return self.get_queryset().recent(n)

    def with_related(self):
        return self.get_queryset().with_related()
