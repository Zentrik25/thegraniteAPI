"""
models.py — Core content models for The Granite Post CMS.

Designed for editorial workflow at a news publication:
  - Article lifecycle: draft → review → published → archived
  - Slug collision safety via counter loop with UUID fallback
  - Auto-stamp published_at on first publish; preserve on archive
  - SEO and Open Graph metadata baked in at the model layer
  - Composite DB indexes tuned for homepage, author, and category queries
  - Breaking news flag
  - 6-slot top story grid, each slot enforced unique at DB level
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class TimeStampedModel(models.Model):
    """Mixin that adds created_at / updated_at to every concrete model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PublishStatus(models.TextChoices):
    """
    Linear editorial lifecycle.

    DRAFT     — being written, not visible to readers
    REVIEW    — submitted for editorial sign-off
    PUBLISHED — live on the site; published_at is stamped automatically
    ARCHIVED  — removed from live feeds but preserved for the record
    """

    DRAFT     = "draft",     "Draft"
    REVIEW    = "review",    "In Review"
    PUBLISHED = "published", "Published"
    ARCHIVED  = "archived",  "Archived"


# Statuses that should carry a published_at timestamp.
PUBLISHED_STATES = frozenset([PublishStatus.PUBLISHED, PublishStatus.ARCHIVED])

# Valid top story rank range.
TOP_STORY_MIN = 1
TOP_STORY_MAX = 6


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def _unique_slug(model_class, base_text: str, fallback: str, max_base: int, current_pk=None) -> str:
    """
    Generate a URL-safe slug that is unique within *model_class*.

    Strategy:
      1. Slugify and truncate to *max_base* characters.
      2. If no collisions, return as-is.
      3. On collision, append an incrementing counter up to 99 attempts.
      4. Beyond 99 collisions, append a 6-char UUID fragment — guaranteed unique.
    """
    base_slug = slugify(base_text)[:max_base] or fallback
    slug = base_slug
    counter = 1

    while model_class.objects.filter(slug=slug).exclude(pk=current_pk).exists():
        if counter > 99:
            slug = f"{base_slug[:max_base - 7]}-{uuid.uuid4().hex[:6]}"
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

class Category(TimeStampedModel):
    """
    Top-level editorial section (e.g. News, Sport, Business).

    Slugs are auto-generated from *name* on first save and never overwritten,
    so renaming a category does NOT silently break existing URLs.
    """

    name        = models.CharField(max_length=100, unique=True)
    slug        = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    og_image_url = models.URLField(
        blank=True,
        help_text="Open Graph image shown when this section is shared on social media.",
    )

    class Meta:
        ordering       = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(Category, self.name, "category", 100, self.pk)
        super().save(*args, **kwargs)


class Tag(TimeStampedModel):
    """
    Free-form keyword tag. Many-to-many with Article.

    Tags are lowercase-normalised on save so 'AI' and 'ai' resolve to the
    same record rather than creating duplicates.
    """

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.name = self.name.strip().lower()
        if not self.slug:
            self.slug = _unique_slug(Tag, self.name, "tag", 80, self.pk)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

class Article(TimeStampedModel):
    """
    The central content object — a single news article or feature piece.

    Key design decisions
    --------------------
    * published_at is stamped automatically the first time status transitions
      to PUBLISHED, and preserved when the article is ARCHIVED.

    * top_story_rank is an integer 1–6 representing a slot in the top story
      grid. Rank 1 is the lead (largest) slot. Each rank may be held by only
      one article at a time — enforced by UniqueConstraint on PostgreSQL and
      by the pre_save signal for all backends.

    * is_breaking is manually cleared by editors. Add a breaking_until
      DateTimeField if time-based auto-expiry is needed.

    * Images are stored as CDN URLs, not file uploads.
    """

    # ------------------------------------------------------------------
    # Core content
    # ------------------------------------------------------------------

    title = models.CharField(max_length=255)
    slug  = models.SlugField(
        max_length=280,
        unique=True,
        blank=True,
        help_text="Auto-generated from title. Changing after publication breaks existing URLs.",
    )
    excerpt = models.TextField(
        blank=True,
        help_text="One or two sentence summary used in listings and meta description fallback.",
    )
    body = models.TextField(
        help_text="Full article body. Supports HTML or Markdown depending on your renderer.",
    )

    # ------------------------------------------------------------------
    # Editorial workflow
    # ------------------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=PublishStatus.choices,
        default=PublishStatus.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Set automatically when the article is first published. Do not edit manually.",
    )

    # ------------------------------------------------------------------
    # Editorial placement flags
    # ------------------------------------------------------------------

    is_breaking = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Tick to display a BREAKING banner. "
            "Untick manually once the story has developed."
        ),
    )

    top_story_rank = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Top story grid slot: 1 (lead/hero) through 6. "
            "Leave blank if not in the top story grid. "
            "Each rank can only be held by one article at a time."
        ),
    )

    # ------------------------------------------------------------------
    # Taxonomy
    # ------------------------------------------------------------------

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
        help_text="Primary editorial section. Required for live articles in most templates.",
    )
    tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name="articles",
    )

    # ------------------------------------------------------------------
    # Authorship
    # ------------------------------------------------------------------

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,   # Never silently delete an author's byline.
        related_name="articles",
    )

    # ------------------------------------------------------------------
    # Featured / hero placement (homepage widget, separate from top story)
    # ------------------------------------------------------------------

    featured_rank = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="1 = hero slot on the homepage widget. Leave blank if not featured.",
    )

    # ------------------------------------------------------------------
    # Media — external CDN URLs (not file uploads)
    # ------------------------------------------------------------------

    image_url = models.URLField(
        blank=True,
        help_text="Absolute URL of the lead image hosted on your CDN. Not a file upload.",
    )
    image_alt     = models.CharField(
        max_length=255,
        blank=True,
        help_text="Alt text for accessibility. Describe the image content, not its style.",
    )
    image_caption = models.CharField(max_length=255, blank=True)
    image_credit  = models.CharField(
        max_length=255,
        blank=True,
        help_text="Photographer / agency credit shown beneath the image.",
    )

    # ------------------------------------------------------------------
    # SEO & Open Graph
    # ------------------------------------------------------------------

    og_title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Overrides title in <title> tag and og:title. Keep under 60 characters.",
    )
    og_description = models.CharField(
        max_length=160,
        blank=True,
        help_text="Meta description and og:description. Keep under 160 characters.",
    )
    og_image_url = models.URLField(
        blank=True,
        help_text="Social share image. Falls back to image_url if blank. Recommended: 1200x630 px.",
    )
    canonical_url = models.URLField(
        blank=True,
        help_text="Set only when this article is a copy of content published elsewhere first.",
    )

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(fields=["status", "published_at"],           name="article_status_pub_idx"),
            models.Index(fields=["author", "status"],                 name="article_author_status_idx"),
            models.Index(fields=["category", "status", "published_at"], name="article_cat_status_pub_idx"),
            models.Index(fields=["featured_rank"],                    name="article_featured_rank_idx"),
            models.Index(fields=["is_breaking", "published_at"],      name="article_breaking_pub_idx"),
            models.Index(fields=["top_story_rank"],                   name="article_top_story_rank_idx"),
        ]
        constraints = [
            # top_story_rank must be 1–6 when set.
            models.CheckConstraint(
                condition=(
                    models.Q(top_story_rank__isnull=True) |
                    models.Q(top_story_rank__gte=TOP_STORY_MIN, top_story_rank__lte=TOP_STORY_MAX)
                ),
                name="article_top_story_rank_1_to_6",
            ),
            # Only one article per rank slot (PostgreSQL; SQLite ignores the condition in dev).
            models.UniqueConstraint(
                fields=["top_story_rank"],
                condition=models.Q(top_story_rank__isnull=False),
                name="article_unique_top_story_rank",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    # ------------------------------------------------------------------
    # Save logic
    # ------------------------------------------------------------------

    def save(self, *args, **kwargs) -> None:
        # 1. Auto-generate slug on first creation only.
        #    Never regenerate on update — that would break live URLs.
        if not self.slug:
            self.slug = _unique_slug(Article, self.title, "article", 240, self.pk)

        # 2. Stamp published_at the first time the article goes live.
        if self.status == PublishStatus.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()

        # 3. Clear published_at for brand-new records saved directly as
        #    draft/review that somehow arrive with a timestamp already set.
        if self.status not in PUBLISHED_STATES and self.pk is None:
            self.published_at = None

        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def seo_title(self) -> str:
        """Best available title for <title> / og:title."""
        return self.og_title or self.title

    @property
    def seo_description(self) -> str:
        """Best available description for meta / og:description."""
        return self.og_description or self.excerpt

    @property
    def resolved_og_image(self) -> str:
        """Social share image, falling back to the article lead image."""
        return self.og_image_url or self.image_url

    @property
    def is_featured(self) -> bool:
        """True if this article occupies any featured slot on the homepage widget."""
        return self.featured_rank is not None

    @property
    def is_top_story(self) -> bool:
        """True if this article occupies any of the 6 top story grid slots."""
        return self.top_story_rank is not None

    @property
    def is_live(self) -> bool:
        """True if the article is currently visible to readers."""
        return self.status == PublishStatus.PUBLISHED

    @property
    def needs_banner(self) -> bool:
        """True if the article requires any editorial badge — breaking or top story."""
        return self.is_breaking or self.is_top_story
