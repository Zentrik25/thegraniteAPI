from django.contrib import admin
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    AdCampaign,
    AdCampaignStatus,
    Advertiser,
    AdZone,
    make_zone_cache_key,
)

_STATUS_COLOURS = {
    "draft":     "#6b7280",
    "active":    "#16a34a",
    "paused":    "#d97706",
    "completed": "#2563eb",
    "cancelled": "#dc2626",
}


def _badge(text: str, colour: str) -> str:
    return format_html(
        '<span style="background:{c};color:#fff;padding:2px 8px;'
        'border-radius:4px;font-size:11px;font-weight:700;">{t}</span>',
        c=colour,
        t=text,
    )


def _invalidate_campaign_zone_caches(queryset) -> None:
    slugs = queryset.values_list("zone__slug", flat=True).distinct()
    for slug in slugs:
        cache.delete(make_zone_cache_key(slug))


@admin.register(AdZone)
class AdZoneAdmin(admin.ModelAdmin):
    list_display    = ("name", "zone_type", "dimensions", "max_ads", "is_active", "active_campaign_count", "created_at")
    list_filter     = ("zone_type", "is_active")
    search_fields   = ("name", "slug", "description")
    ordering        = ("name",)
    readonly_fields = ("slug", "created_at", "updated_at")

    fieldsets = (
        (None, {
            "fields": ("name", "slug", "zone_type", "description"),
        }),
        ("Placement", {
            "fields": ("width", "height", "max_ads", "is_active"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        today = timezone.localdate()
        return super().get_queryset(request).annotate(
            _active_campaign_count=Count(
                "campaigns",
                filter=Q(
                    campaigns__status=AdCampaignStatus.ACTIVE,
                    campaigns__start_date__lte=today,
                    campaigns__end_date__gte=today,
                ),
                distinct=True,
            )
        )

    @admin.display(description="Dimensions")
    def dimensions(self, obj):
        return f"{obj.width} x {obj.height}px"

    @admin.display(description="Running Campaigns", ordering="_active_campaign_count")
    def active_campaign_count(self, obj):
        return obj._active_campaign_count


@admin.register(Advertiser)
class AdvertiserAdmin(admin.ModelAdmin):
    list_display    = ("company_name", "contact_name", "contact_email", "is_active", "campaign_count", "created_at")
    list_filter     = ("is_active", "created_at")
    search_fields   = ("company_name", "contact_name", "contact_email")
    ordering        = ("company_name",)
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Advertiser", {
            "fields": ("company_name", "contact_name", "contact_email", "contact_phone", "website_url"),
        }),
        ("Status", {
            "fields": ("is_active",),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _campaign_count=Count("campaigns", distinct=True)
        )

    @admin.display(description="Campaigns", ordering="_campaign_count")
    def campaign_count(self, obj):
        return obj._campaign_count


@admin.register(AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "advertiser",
        "zone",
        "status_badge",
        "ctr_display",
        "running_badge",
        "date_range",
        "total_impressions",
        "total_clicks",
    )
    list_filter        = ("status", "zone", "advertiser", "start_date", "end_date")
    search_fields      = ("name", "advertiser__company_name", "zone__name")
    ordering           = ("-created_at",)
    list_select_related = ("advertiser", "zone")
    readonly_fields = (
        "ctr_display",
        "running_badge",
        "impression_stats",
        "click_stats",
        "total_impressions",
        "total_clicks",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Campaign", {
            "fields": ("advertiser", "name", "zone", "status"),
        }),
        ("Creative", {
            "fields": ("creative_url", "click_url", "alt_text"),
        }),
        ("Schedule & Budget", {
            "fields": (
                "start_date",
                "end_date",
                "total_budget",
                "cost_per_impression",
                "cost_per_click",
                "impression_cap",
                "click_cap",
            ),
        }),
        ("Performance", {
            "fields": (
                "ctr_display",
                "running_badge",
                "total_impressions",
                "total_clicks",
                "impression_stats",
                "click_stats",
            ),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    actions = ["action_pause", "action_activate"]

    @admin.action(description="Pause selected campaigns")
    def action_pause(self, request, queryset):
        updated = queryset.exclude(status=AdCampaignStatus.PAUSED).update(
            status=AdCampaignStatus.PAUSED,
            updated_at=timezone.now(),
        )
        _invalidate_campaign_zone_caches(queryset)
        self.message_user(request, f"{updated} campaign(s) paused.")

    @admin.action(description="Activate selected campaigns")
    def action_activate(self, request, queryset):
        updated = queryset.exclude(status=AdCampaignStatus.ACTIVE).update(
            status=AdCampaignStatus.ACTIVE,
            updated_at=timezone.now(),
        )
        _invalidate_campaign_zone_caches(queryset)
        self.message_user(request, f"{updated} campaign(s) activated.")

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return _badge(obj.status.upper(), _STATUS_COLOURS.get(obj.status, "#6b7280"))

    @admin.display(description="CTR")
    def ctr_display(self, obj):
        return f"{obj.ctr:.2f}%"

    @admin.display(description="Running")
    def running_badge(self, obj):
        if obj.is_running:
            return _badge("RUNNING", "#16a34a")
        return _badge("STOPPED", "#6b7280")

    @admin.display(description="Date Range")
    def date_range(self, obj):
        return f"{obj.start_date:%Y-%m-%d} -> {obj.end_date:%Y-%m-%d}"

    @admin.display(description="Impression Stats")
    def impression_stats(self, obj):
        if not obj.pk:
            return "Save campaign to view stats."
        return f"{obj.impressions.count()} logged impression row(s)."

    @admin.display(description="Click Stats")
    def click_stats(self, obj):
        if not obj.pk:
            return "Save campaign to view stats."
        return f"{obj.clicks.count()} logged click row(s)."
