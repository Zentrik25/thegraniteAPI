from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from .models import Section


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "slug",
        "display_order",
        "is_active_badge",
        "is_primary_badge",
        "category_count_display",
        "article_count_display",
        "featured_article",
        "updated_at",
    )
    list_editable       = ("display_order",)
    list_filter         = ("is_active", "is_primary")
    search_fields       = ("name", "slug", "description")
    ordering            = ("display_order", "name")
    readonly_fields     = ("slug", "created_at", "updated_at")
    autocomplete_fields = ["featured_article"]

    fieldsets = (
        ("Section", {
            "fields": (
                "name", "slug", "description",
                "display_order", "is_active", "is_primary",
            ),
        }),
        ("Featured Article", {
            "fields": ("featured_article",),
            "description": (
                "Pin an article as the hero on this section's landing page. "
                "If not set the most recent article is used automatically."
            ),
        }),
        ("Social / SEO", {
            "fields":  ("og_image_url",),
            "classes": ("collapse",),
        }),
        ("Audit", {
            "fields":  ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    actions = [
        "action_activate",
        "action_deactivate",
        "action_make_primary",
        "action_make_secondary",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _article_count  = Count("categories__articles", distinct=True),
            _category_count = Count("categories",           distinct=True),
        ).select_related("featured_article")

    @admin.action(description="✅  Activate selected sections")
    def action_activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} section(s) activated.")

    @admin.action(description="🚫  Deactivate selected sections")
    def action_deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} section(s) deactivated.")

    @admin.action(description="⭐  Make primary (main nav)")
    def action_make_primary(self, request, queryset):
        updated = queryset.update(is_primary=True)
        self.message_user(request, f"{updated} section(s) set as primary.")

    @admin.action(description="▽  Make secondary (dropdown/footer)")
    def action_make_secondary(self, request, queryset):
        updated = queryset.update(is_primary=False)
        self.message_user(request, f"{updated} section(s) set as secondary.")

    @admin.display(description="Active", ordering="is_active")
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background:#16a34a;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
                "ACTIVE",
            )
        return format_html(
            '<span style="background:#dc2626;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
            "INACTIVE",
        )

    @admin.display(description="Nav", ordering="is_primary")
    def is_primary_badge(self, obj):
        if obj.is_primary:
            return format_html(
                '<span style="background:#2563eb;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
                "PRIMARY",
            )
        return format_html(
            '<span style="background:#6b7280;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
            "SECONDARY",
        )

    @admin.display(description="Articles", ordering="_article_count")
    def article_count_display(self, obj):
        return obj._article_count

    @admin.display(description="Categories", ordering="_category_count")
    def category_count_display(self, obj):
        return obj._category_count
