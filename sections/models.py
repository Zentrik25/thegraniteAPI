from django.db import models
from django.utils.text import slugify


class Section(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Section name e.g. News, Sport, Business.",
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        help_text="Auto-generated from name. Never changes after creation.",
    )
    description = models.TextField(
        blank=True,
        help_text="Short description shown on the section landing page.",
    )
    og_image_url = models.URLField(
        blank=True,
        help_text="Open Graph image for social sharing. Recommended: 1200x630px.",
    )
    display_order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Navigation order. Lower numbers appear first. News=1, Sport=2.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Inactive sections are hidden from navigation and the API. "
                  "All categories and articles inside are preserved.",
    )
    is_primary = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Primary sections appear in the main navigation bar. "
                  "Secondary sections appear in a dropdown or footer menu.",
    )
    featured_article = models.ForeignKey(
        "articles.Article",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="featured_in_sections",
        help_text="Pinned article shown as the hero on this section's landing page. "
                  "If not set the most recent article is used.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering        = ["display_order", "name"]
        verbose_name_plural = "Sections"
        indexes = [
            models.Index(
                fields=["is_active", "display_order"],
                name="sections_active_order_idx",
            ),
            models.Index(
                fields=["is_active", "is_primary", "display_order"],
                name="sections_primary_order_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            base_slug = slugify(self.name)[:100] or "section"
            slug      = base_slug
            counter   = 1
            while Section.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug    = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def article_count(self) -> int:
        from articles.models import Article, PublishStatus
        return Article.objects.filter(
            category__section=self,
            status=PublishStatus.PUBLISHED,
        ).count()

    @property
    def category_count(self) -> int:
        return self.categories.count()

    def get_latest_articles(self, n: int = 20):
        from articles.models import Article, PublishStatus
        return (
            Article.objects
            .filter(
                category__section=self,
                status=PublishStatus.PUBLISHED,
            )
            .with_related()
            .order_by("-published_at")[:n]
        )

    def get_hero_article(self):
        if self.featured_article_id:
            return self.featured_article
        return self.get_latest_articles(n=1).first()