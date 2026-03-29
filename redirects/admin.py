from django.contrib import admin
from django.utils.html import format_html

from .models import Redirect


@admin.register(Redirect)
class RedirectAdmin(admin.ModelAdmin):

    list_display   = (
        "old_path",
        "new_path",
        "is_active_badge",
        "hits",
        "created_by",
        "created_at",
    )
    list_filter    = ("is_active", "created_by")
    search_fields  = ("old_path", "new_path", "note")
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = ("hits", "created_by", "created_at", "updated_at")

    fieldsets = (
        ("Redirect", {
            "fields": ("old_path", "new_path", "is_active"),
        }),
        ("Details", {
            "fields": ("note",),
        }),
        ("Stats", {
            "fields":  ("hits", "created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    actions = ["action_activate", "action_deactivate"]

    @admin.action(description="✅  Activate selected redirects")
    def action_activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} redirect(s) activated.")

    @admin.action(description="🚫  Deactivate selected redirects")
    def action_deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} redirect(s) deactivated.")

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