from django.contrib import admin
from django.utils.html import format_html

from .models import Subscriber


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):

    list_display   = (
        "email", "confirmed_badge", "source",
        "confirmed_at", "created_at",
    )
    list_filter    = ("confirmed", "source")
    search_fields  = ("email",)
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"

    readonly_fields = (
        "confirmation_token",
        "unsubscribe_token",
        "confirmed_at",
        "created_at",
    )

    fieldsets = (
        (None, {
            "fields": ("email", "confirmed", "source"),
        }),
        ("Tokens", {
            "fields": ("confirmation_token", "unsubscribe_token"),
            "classes": ("collapse",),
        }),
        ("Dates", {
            "fields": ("confirmed_at", "created_at"),
            "classes": ("collapse",),
        }),
    )

    actions = ["action_confirm", "action_delete_unconfirmed"]

    @admin.action(description="✅  Mark selected as confirmed")
    def action_confirm(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(confirmed=False).update(
            confirmed    = True,
            confirmed_at = timezone.now(),
        )
        self.message_user(request, f"{updated} subscriber(s) confirmed.")

    @admin.action(description="🗑️  Delete unconfirmed subscribers")
    def action_delete_unconfirmed(self, request, queryset):
        deleted, _ = queryset.filter(confirmed=False).delete()
        self.message_user(request, f"{deleted} unconfirmed subscriber(s) deleted.")

    @admin.display(description="Status", ordering="confirmed")
    def confirmed_badge(self, obj):
        if obj.confirmed:
            return format_html(
                '<span style="background:#16a34a;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:11px;font-weight:700;">CONFIRMED</span>'
            )
        return format_html(
            '<span style="background:#d97706;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:700;">PENDING</span>'
        )
