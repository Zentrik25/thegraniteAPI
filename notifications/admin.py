from django.contrib import admin
from django.utils.html import format_html

from .models import Notification, PushSubscription


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):

    list_display = (
        "short_id",
        "is_active_badge",
        "user_agent_short",
        "created_at",
        "last_used",
    )
    list_filter    = ("is_active",)
    search_fields  = ("endpoint", "user_agent")
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "id", "endpoint", "p256dh", "auth",
        "user_agent", "created_at", "last_used",
    )

    def has_add_permission(self, request) -> bool:
        return False

    @admin.display(description="ID")
    def short_id(self, obj):
        return str(obj.pk)[:8] + "..."

    @admin.display(description="Status", ordering="is_active")
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background:#16a34a;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:11px;font-weight:700;">ACTIVE</span>'
            )
        return format_html(
            '<span style="background:#6b7280;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:700;">INACTIVE</span>'
        )

    @admin.display(description="Browser")
    def user_agent_short(self, obj):
        return obj.user_agent[:80] if obj.user_agent else "Unknown"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):

    list_display = (
        "title",
        "article",
        "sent_count",
        "success_count",
        "failed_count",
        "sent_at",
    )
    search_fields  = ("title", "body")
    ordering       = ("-sent_at",)
    date_hierarchy = "sent_at"
    readonly_fields = (
        "article", "title", "body", "url",
        "icon_url", "sent_count", "success_count",
        "failed_count", "sent_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False