"""
admin.py — Django admin for reader accounts.

Features:
  - ReaderAccountAdmin: search, filters, bookmark count column, bulk actions
  - Bulk actions: verify email, deactivate, reactivate
  - ReadingHistoryInline: most recent reads on the detail page
  - Bookmark count cached per reader (TTL 60 s) for list performance
  - Sensitive fields (password, tokens) excluded from the detail form
"""

from django.contrib import admin
from django.core.cache import cache

from .models import BlacklistedReaderToken, Bookmark, ReadingHistory, ReaderAccount


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class ReadingHistoryInline(admin.TabularInline):
    """Compact reading history shown on the ReaderAccount detail page."""

    model            = ReadingHistory
    extra            = 0
    max_num          = 20
    can_delete       = True
    show_change_link = True
    readonly_fields  = ("article", "read_at", "read_count")
    fields           = ("article", "read_at", "read_count")
    ordering         = ("-read_at",)


# ---------------------------------------------------------------------------
# ReaderAccount
# ---------------------------------------------------------------------------

@admin.register(ReaderAccount)
class ReaderAccountAdmin(admin.ModelAdmin):
    """
    Admin interface for reader accounts.

    Passwords and token fields are excluded from all forms — they must
    only be modified via the dedicated endpoints.
    """

    list_display = (
        "username",
        "email",
        "is_active",
        "is_email_verified",
        "bookmark_count_display",
        "date_joined",
        "last_login",
    )
    list_filter      = ("is_active", "is_email_verified")
    search_fields    = ("username", "email", "display_name")
    ordering         = ("-date_joined",)
    list_per_page    = 25
    show_facets      = admin.ShowFacets.NEVER
    readonly_fields  = (
        "id",
        "email_verification_token",
        "date_joined",
        "last_login",
    )

    fieldsets = (
        ("Identity", {
            "fields": (
                "id",
                "email",
                "username",
                "display_name",
                "avatar_url",
                "bio",
            ),
        }),
        ("Account Status", {
            "fields": (
                "is_active",
                "is_email_verified",
                "email_verification_token",
            ),
        }),
        ("Timestamps", {
            "fields": ("date_joined", "last_login"),
            "classes": ("collapse",),
        }),
    )

    inlines = [ReadingHistoryInline]

    actions = [
        "action_verify_email",
        "action_deactivate",
        "action_reactivate",
    ]

    @admin.display(description="Bookmarks")
    def bookmark_count_display(self, obj) -> int:
        """Cached bookmark count — avoids a query per row on large lists."""
        key   = f"accounts:bookmarks:count:{obj.id}"
        count = cache.get(key)
        if count is None:
            count = obj.bookmarks.count()
            cache.set(key, count, 60)
        return count

    @admin.action(description="✅  Verify email for selected readers")
    def action_verify_email(self, request, queryset):
        updated = queryset.filter(is_email_verified=False).update(
            is_email_verified=True,
        )
        self.message_user(request, f"{updated} reader(s) email verified.")

    @admin.action(description="🚫  Deactivate selected readers")
    def action_deactivate(self, request, queryset):
        updated = queryset.filter(is_active=True).update(is_active=False)
        self.message_user(request, f"{updated} reader(s) deactivated.")

    @admin.action(description="🔄  Reactivate selected readers")
    def action_reactivate(self, request, queryset):
        updated = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(request, f"{updated} reader(s) reactivated.")


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------

@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    """Admin for individual bookmarks — mainly useful for debugging."""

    list_display  = ("reader", "article", "created_at")
    search_fields = ("reader__username", "reader__email", "article__title")
    raw_id_fields = ("reader", "article")
    ordering      = ("-created_at",)
    list_per_page = 50


@admin.register(ReadingHistory)
class ReadingHistoryAdmin(admin.ModelAdmin):
    """Admin for reading history entries."""

    list_display  = ("reader", "article", "read_count", "read_at")
    search_fields = ("reader__username", "article__title")
    raw_id_fields = ("reader", "article")
    ordering      = ("-read_at",)
    list_per_page = 50


@admin.register(BlacklistedReaderToken)
class BlacklistedReaderTokenAdmin(admin.ModelAdmin):
    """Admin for revoked reader JWT refresh tokens."""

    list_display    = ("jti", "blacklisted_at")
    search_fields   = ("jti",)
    ordering        = ("-blacklisted_at",)
    list_per_page   = 50
    readonly_fields = ("jti", "blacklisted_at")
