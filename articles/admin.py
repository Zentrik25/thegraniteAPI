"""
admin.py — Django admin for The Granite Post articles app.

Features:
  - Colour-coded status badges in the list view
  - BREAKING label and TOP 1–6 rank badge per article row
  - Top story slot visualiser (readonly panel showing all 6 slots)
  - SEO preview panel on the detail page
  - Bulk actions: publish, unpublish, send to review, archive,
    mark/clear breaking
  - save_model atomically displaces any article already in the
    target top story slot before the DB constraint fires
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html, mark_safe

from .models import Article, Category, Tag, TOP_STORY_MAX, TOP_STORY_MIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATUS_COLOURS = {
    "draft":     "#6b7280",
    "review":    "#d97706",
    "published": "#16a34a",
    "archived":  "#dc2626",
}

_RANK_COLOURS = {
    1: "#92400e",   # amber-900  — lead slot
    2: "#5b21b6",   # violet-800
    3: "#1e40af",   # blue-800
    4: "#065f46",   # emerald-800
    5: "#075985",   # sky-800
    6: "#374151",   # gray-700
}


def _badge(text: str, colour: str) -> str:
    return format_html(
        '<span style="background:{c};color:#fff;padding:2px 8px;'
        'border-radius:4px;font-size:11px;font-weight:700;">{t}</span>',
        c=colour, t=text,
    )


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display    = ("name", "slug", "article_count", "created_at")
    search_fields   = ("name", "slug")
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering        = ("name",)

    fieldsets = (
        (None, {"fields": ("name", "slug", "description")}),
        ("Social / SEO", {"fields": ("og_image_url",), "classes": ("collapse",)}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Articles")
    def article_count(self, obj):
        return obj.articles.count()


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display    = ("name", "slug", "article_count", "created_at")
    search_fields   = ("name", "slug")
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering        = ("name",)

    @admin.display(description="Articles")
    def article_count(self, obj):
        return obj.articles.count()


# ---------------------------------------------------------------------------
# Article — custom filters
# ---------------------------------------------------------------------------

class BreakingListFilter(admin.SimpleListFilter):
    title          = "breaking news"
    parameter_name = "breaking"

    def lookups(self, request, model_admin):
        return (("yes", "Breaking only"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(is_breaking=True)
        return queryset


class TopStoryListFilter(admin.SimpleListFilter):
    title          = "top story"
    parameter_name = "top_story"

    def lookups(self, request, model_admin):
        return (("yes", "In top story grid"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(top_story_rank__isnull=False)
        return queryset


# ---------------------------------------------------------------------------
# Article admin
# ---------------------------------------------------------------------------

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):

    # ------------------------------------------------------------------
    # List view
    # ------------------------------------------------------------------

    list_display = (
        "title",
        "status_badge",
        "breaking_flag",
        "top_story_badge",
        "category",
        "author",
        "published_at",
        "created_at",
    )
    list_filter = (
        "status",
        BreakingListFilter,
        TopStoryListFilter,
        "category",
        "author",
    )
    search_fields  = ("title", "excerpt", "body", "slug")
    date_hierarchy = "created_at"
    ordering       = ("-created_at",)
    list_per_page  = 25

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------

    readonly_fields = (
        "slug",
        "published_at",
        "created_at",
        "updated_at",
        "seo_preview",
        "top_story_grid",
    )
    filter_horizontal = ("tags",)

    fieldsets = (
        ("Content", {
            "fields": ("title", "slug", "excerpt", "body"),
        }),
        ("Editorial", {
            "fields": ("status", "author", "category", "tags"),
        }),
        ("Placement", {
            "description": (
                "Top story grid has 6 slots — rank 1 is the lead (largest) article. "
                "Assigning a rank displaces any article currently in that slot. "
                "Leave blank to remove this article from the top story grid."
            ),
            "fields": (
                "is_breaking",
                "top_story_rank",
                "top_story_grid",
                "featured_rank",
            ),
        }),
        ("Lead Image", {
            "fields": ("image_url", "image_alt", "image_caption", "image_credit"),
            "classes": ("collapse",),
        }),
        ("SEO & Open Graph", {
            "fields": (
                "og_title", "og_description", "og_image_url",
                "canonical_url", "seo_preview",
            ),
            "classes": ("collapse",),
        }),
        ("Audit", {
            "fields": ("published_at", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    # ------------------------------------------------------------------
    # Bulk actions
    # ------------------------------------------------------------------

    actions = [
        "action_publish",
        "action_unpublish",
        "action_send_to_review",
        "action_archive",
        "action_mark_breaking",
        "action_clear_breaking",
    ]

    @admin.action(description="✅  Publish selected articles")
    def action_publish(self, request, queryset):
        updated = 0
        for article in queryset.exclude(status="published"):
            article.status = "published"
            article.save()
            updated += 1
        self.message_user(request, f"{updated} article(s) published.")

    @admin.action(description="↩️  Unpublish → Draft selected articles")
    def action_unpublish(self, request, queryset):
        updated = queryset.exclude(status="draft").update(
            status="draft", updated_at=timezone.now(),
        )
        self.message_user(request, f"{updated} article(s) moved back to draft.")

    @admin.action(description="🔎  Send selected articles to Review")
    def action_send_to_review(self, request, queryset):
        updated = queryset.filter(status="draft").update(
            status="review", updated_at=timezone.now(),
        )
        self.message_user(request, f"{updated} article(s) sent to review.")

    @admin.action(description="🗄️  Archive selected articles")
    def action_archive(self, request, queryset):
        updated = queryset.exclude(status="archived").update(
            status="archived", updated_at=timezone.now(),
        )
        self.message_user(request, f"{updated} article(s) archived.")

    @admin.action(description="🔴  Mark selected as Breaking News")
    def action_mark_breaking(self, request, queryset):
        updated = queryset.update(is_breaking=True, updated_at=timezone.now())
        self.message_user(request, f"{updated} article(s) marked as breaking.")

    @admin.action(description="⚪  Clear Breaking News flag")
    def action_clear_breaking(self, request, queryset):
        updated = queryset.update(is_breaking=False, updated_at=timezone.now())
        self.message_user(request, f"{updated} article(s) breaking flag cleared.")

    # ------------------------------------------------------------------
    # Custom display columns
    # ------------------------------------------------------------------

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colour = _STATUS_COLOURS.get(obj.status, "#6b7280")
        return _badge(obj.status.upper(), colour)

    @admin.display(description="🔴 Breaking")
    def breaking_flag(self, obj):
        if obj.is_breaking:
            return _badge("BREAKING", "#dc2626")
        return ""

    @admin.display(description="Top Slot", ordering="top_story_rank")
    def top_story_badge(self, obj):
        if obj.top_story_rank is not None:
            colour = _RANK_COLOURS.get(obj.top_story_rank, "#374151")
            return _badge(f"TOP {obj.top_story_rank}", colour)
        return ""

    # ------------------------------------------------------------------
    # Top story grid — readonly visualiser shown on the detail page
    # ------------------------------------------------------------------

    @admin.display(description="Top Story Grid (current)")
    def top_story_grid(self, obj):
        """
        Render a visual overview of all 6 top story slots showing which
        article occupies each rank. Helps editors see at a glance what
        will be displaced if they assign a new rank to this article.
        """
        # Fetch all articles currently in the grid in one query.
        occupied = {
            a.top_story_rank: a
            for a in Article.objects.filter(
                top_story_rank__isnull=False,
                status="published",
            ).only("pk", "title", "top_story_rank")
        }

        rows = []
        for rank in range(TOP_STORY_MIN, TOP_STORY_MAX + 1):
            colour    = _RANK_COLOURS.get(rank, "#374151")
            rank_cell = (
                f'<span style="background:{colour};color:#fff;padding:2px 10px;'
                f'border-radius:4px;font-size:12px;font-weight:700;'
                f'min-width:54px;display:inline-block;text-align:center;">'
                f'SLOT {rank}</span>'
            )

            if rank in occupied:
                article   = occupied[rank]
                is_this   = article.pk == obj.pk
                title_str = (
                    f'<strong>{article.title}</strong>'
                    if is_this
                    else f'<span style="color:#374151;">{article.title}</span>'
                )
                suffix = (
                    ' <em style="color:#16a34a;font-size:11px;">(this article)</em>'
                    if is_this else ""
                )
                content = f'{title_str}{suffix}'
            else:
                content = '<span style="color:#9ca3af;font-style:italic;">— empty —</span>'

            rows.append(
                f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:6px 12px 6px 0;">{rank_cell}</td>'
                f'<td style="padding:6px 0;">{content}</td>'
                f'</tr>'
            )

        return format_html(
            '<table style="border-collapse:collapse;width:100%;max-width:640px;">'
            '<thead><tr>'
            '<th style="text-align:left;padding:4px 12px 4px 0;font-size:11px;'
            'color:#6b7280;text-transform:uppercase;">Rank</th>'
            '<th style="text-align:left;padding:4px 0;font-size:11px;'
            'color:#6b7280;text-transform:uppercase;">Article</th>'
            '</tr></thead>'
            '<tbody>{}</tbody>'
            '</table>',
            mark_safe("".join(rows)),
        )

    # ------------------------------------------------------------------
    # SEO preview — readonly panel on the detail page
    # ------------------------------------------------------------------

    @admin.display(description="SEO Preview")
    def seo_preview(self, obj):
        title = obj.seo_title or "Article Title"
        desc  = obj.seo_description or "Article description will appear here."
        slug  = obj.slug or "article-slug"
        return format_html(
            """
            <div style="font-family:Arial,sans-serif;max-width:600px;
                        border:1px solid #e5e7eb;border-radius:6px;padding:12px 16px;">
              <div style="font-size:12px;color:#16a34a;margin-bottom:2px;">
                thegranite.co.zw › {slug}
              </div>
              <div style="font-size:18px;color:#1a0dab;margin-bottom:4px;">{title}</div>
              <div style="font-size:13px;color:#4d5156;">{desc}</div>
            </div>
            """,
            slug=slug, title=title, desc=desc,
        )

    # ------------------------------------------------------------------
    # Save override — displace any existing article in the target rank
    # before the DB UniqueConstraint fires
    # ------------------------------------------------------------------

    def save_model(self, request, obj, form, change):
        if obj.top_story_rank is not None:
            Article.objects.exclude(pk=obj.pk).filter(
                top_story_rank=obj.top_story_rank
            ).update(top_story_rank=None, updated_at=timezone.now())
        super().save_model(request, obj, form, change)
