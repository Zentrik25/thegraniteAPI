from django.contrib import admin
from django.utils.html import format_html

from .models import Comment, CommentStatus


class StatusFilter(admin.SimpleListFilter):
    title          = "status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return CommentStatus.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):

    list_display  = (
        "author_name",
        "article_title",
        "status_badge",
        "is_reply",
        "created_at",
    )
    list_filter   = (StatusFilter, "created_at")
    search_fields = ("author_name", "author_email", "body", "article__title")
    ordering      = ("-created_at",)
    readonly_fields = (
        "article", "parent", "author_name", "author_email",
        "body", "ip_hash", "created_at", "updated_at",
    )
    date_hierarchy = "created_at"

    fieldsets = (
        ("Comment", {
            "fields": ("article", "parent", "body"),
        }),
        ("Author", {
            "fields": ("author_name", "author_email", "ip_hash"),
        }),
        ("Moderation", {
            "fields": ("status",),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    actions = ["action_approve", "action_reject"]

    @admin.action(description="✅  Approve selected comments")
    def action_approve(self, request, queryset):
        updated = queryset.update(status=CommentStatus.APPROVED)
        self.message_user(request, f"{updated} comment(s) approved.")

    @admin.action(description="🚫  Reject selected comments")
    def action_reject(self, request, queryset):
        updated = queryset.update(status=CommentStatus.REJECTED)
        self.message_user(request, f"{updated} comment(s) rejected.")

    @admin.display(description="Article")
    def article_title(self, obj):
        return obj.article.title

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colours = {
            "pending":  "#d97706",
            "approved": "#16a34a",
            "rejected": "#dc2626",
        }
        colour = colours.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
            colour,
            obj.status.upper(),
        )

    def has_add_permission(self, request) -> bool:
        return False
