"""
admin.py — Django admin for the subscriptions app.

Registered models:
  SubscriptionPlan — pricing tiers with USD pricing, subscriber count annotation
  Subscription     — reader subscriptions with active/expiry badge and reader email
  Payment          — Paynow payment transactions with USD amounts and status badge

Revenue summary is displayed as a readonly fieldset on the Subscription changelist.
"""

import logging
from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.db.models import Count, Q, QuerySet, Sum
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html

from .models import Payment, PaymentStatus, Subscription, SubscriptionPlan, SubscriptionStatus

logger = logging.getLogger("subscriptions.admin")


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class ActivePlanFilter(admin.SimpleListFilter):
    """Filter subscription plans by active status."""

    title        = "plan status"
    parameter_name = "active"

    def lookups(self, request: HttpRequest, model_admin) -> list[tuple]:
        return [
            ("yes", "Active"),
            ("no", "Inactive"),
        ]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value() == "yes":
            return queryset.filter(is_active=True)
        if self.value() == "no":
            return queryset.filter(is_active=False)
        return queryset


class SubscriptionStatusFilter(admin.SimpleListFilter):
    """Filter subscriptions by status."""

    title          = "subscription status"
    parameter_name = "sub_status"

    def lookups(self, request: HttpRequest, model_admin) -> list[tuple]:
        return SubscriptionStatus.choices

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


class PaymentStatusFilter(admin.SimpleListFilter):
    """Filter payments by status."""

    title          = "payment status"
    parameter_name = "pay_status"

    def lookups(self, request: HttpRequest, model_admin) -> list[tuple]:
        return PaymentStatus.choices

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


# ---------------------------------------------------------------------------
# SubscriptionPlan admin
# ---------------------------------------------------------------------------

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    """
    Admin for SubscriptionPlan.

    Annotates each plan with the current subscriber count.
    All prices shown in USD.
    """

    list_display   = (
        "name",
        "slug",
        "price_usd_display",
        "billing_period",
        "article_access",
        "is_active",
        "subscriber_count",
        "created_at",
    )
    list_filter    = (ActivePlanFilter, "billing_period", "article_access")
    search_fields  = ("name", "slug", "description")
    ordering       = ("price_usd",)
    readonly_fields = ("id", "created_at", "updated_at", "subscriber_count")
    prepopulated_fields = {"slug": ("name",)}

    fieldsets = (
        ("Plan Details", {
            "fields": ("id", "name", "slug", "description"),
        }),
        ("Pricing (USD)", {
            "fields": ("price_usd", "billing_period"),
            "description": "All prices are in USD only.",
        }),
        ("Access & Features", {
            "fields": ("article_access", "features", "is_active"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate with active subscriber count."""
        today = date.today()
        return super().get_queryset(request).annotate(
            _subscriber_count=Count(
                "subscriptions",
                filter=Q(
                    subscriptions__status=SubscriptionStatus.ACTIVE,
                    subscriptions__current_period_end__gte=today,
                ),
            )
        )

    @admin.display(description="Price (USD)", ordering="price_usd")
    def price_usd_display(self, obj) -> str:
        """Format price with USD currency label."""
        return f"${obj.price_usd:.2f} USD"

    @admin.display(description="Active Subscribers", ordering="_subscriber_count")
    def subscriber_count(self, obj) -> int:
        """Return annotated subscriber count."""
        return getattr(obj, "_subscriber_count", 0)


# ---------------------------------------------------------------------------
# Subscription admin
# ---------------------------------------------------------------------------

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """
    Admin for Subscription.

    Displays is_active_subscription as a coloured badge and days_remaining
    for quick triage. Reader email is shown for support queries.
    Bulk actions: cancel selected, extend by 30 days.
    """

    list_display   = (
        "reader_email",
        "plan_name",
        "status_badge",
        "active_badge",
        "days_remaining_display",
        "current_period_end",
        "cancel_at_period_end",
        "created_at",
    )
    list_filter    = (SubscriptionStatusFilter, "plan", "cancel_at_period_end")
    search_fields  = ("reader__email", "reader__username", "paynow_reference")
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"
    list_select_related = ("reader", "plan")
    readonly_fields = (
        "id",
        "reader",
        "started_at",
        "paynow_reference",
        "created_at",
        "updated_at",
        "is_active_display",
        "days_remaining_display",
    )
    actions = ["action_bulk_cancel", "action_bulk_extend_30"]

    fieldsets = (
        ("Subscription", {
            "fields": ("id", "reader", "plan", "status"),
        }),
        ("Billing Period", {
            "fields": (
                "started_at",
                "current_period_start",
                "current_period_end",
                "cancel_at_period_end",
                "cancelled_at",
            ),
        }),
        ("Paynow", {
            "fields": ("paynow_reference",),
        }),
        ("Status", {
            "fields": ("is_active_display", "days_remaining_display"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Reader")
    def reader_email(self, obj) -> str:
        return obj.reader.email

    @admin.display(description="Plan")
    def plan_name(self, obj) -> str:
        return obj.plan.name if obj.plan else "—"

    @admin.display(description="Status")
    def status_badge(self, obj) -> str:
        colour_map = {
            SubscriptionStatus.ACTIVE:    "#2e7d32",
            SubscriptionStatus.TRIALING:  "#1565c0",
            SubscriptionStatus.CANCELLED: "#c62828",
            SubscriptionStatus.EXPIRED:   "#6d4c41",
            SubscriptionStatus.PAST_DUE:  "#e65100",
        }
        colour = colour_map.get(obj.status, "#616161")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:3px;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Active?", boolean=True)
    def active_badge(self, obj) -> bool:
        return obj.is_active_subscription

    @admin.display(description="Days Remaining")
    def days_remaining_display(self, obj) -> str:
        days = obj.days_remaining
        if days < 0:
            return format_html('<span style="color:#c62828;">{} (expired)</span>', abs(days))
        if days <= 7:
            return format_html('<span style="color:#e65100;">{} days</span>', days)
        return f"{days} days"

    @admin.display(description="Is Active")
    def is_active_display(self, obj) -> str:
        return "Yes" if obj.is_active_subscription else "No"

    @admin.action(description="Cancel selected subscriptions immediately")
    def action_bulk_cancel(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Immediately cancel all selected subscriptions."""
        now = timezone.now()
        updated = queryset.filter(
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]
        ).update(
            status=SubscriptionStatus.CANCELLED,
            cancelled_at=now,
        )
        self.message_user(request, f"{updated} subscription(s) cancelled.")
        logger.info("[BulkCancel] Admin %s cancelled %d subscriptions.", request.user, updated)

    @admin.action(description="Extend selected subscriptions by 30 days")
    def action_bulk_extend_30(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Extend current_period_end by 30 days for selected subscriptions."""
        from datetime import timedelta

        extended = 0
        for subscription in queryset.select_for_update():
            subscription.current_period_end = subscription.current_period_end + timedelta(days=30)
            subscription.save(update_fields=["current_period_end", "updated_at"])
            extended += 1

        self.message_user(request, f"{extended} subscription(s) extended by 30 days.")
        logger.info("[BulkExtend] Admin %s extended %d subscriptions.", request.user, extended)


# ---------------------------------------------------------------------------
# Payment admin
# ---------------------------------------------------------------------------

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Admin for Payment.

    Displays USD amounts with status badges and Paynow references.
    Includes a revenue summary at the top of the changelist page.
    No add permission — payments are created by the API only.
    """

    list_display   = (
        "id_short",
        "subscription_reader",
        "amount_usd_display",
        "payment_method",
        "status_badge",
        "paynow_reference",
        "created_at",
    )
    list_filter    = (PaymentStatusFilter, "payment_method", "created_at")
    search_fields  = ("paynow_reference", "subscription__reader__email", "phone_number")
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"
    list_select_related = ("subscription__reader", "subscription__plan")
    readonly_fields = (
        "id",
        "subscription",
        "amount_usd",
        "currency",
        "payment_method",
        "status",
        "paynow_reference",
        "paynow_poll_url",
        "paynow_redirect_url",
        "phone_number",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Payment", {
            "fields": ("id", "subscription", "amount_usd", "currency"),
        }),
        ("Method & Status", {
            "fields": ("payment_method", "status", "phone_number"),
        }),
        ("Paynow", {
            "fields": ("paynow_reference", "paynow_poll_url", "paynow_redirect_url"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Payments are created by the API only."""
        return False

    @admin.display(description="ID")
    def id_short(self, obj) -> str:
        return str(obj.id)[:8] + "…"

    @admin.display(description="Reader")
    def subscription_reader(self, obj) -> str:
        return obj.subscription.reader.email if obj.subscription else "—"

    @admin.display(description="Amount (USD)", ordering="amount_usd")
    def amount_usd_display(self, obj) -> str:
        return f"${obj.amount_usd:.2f} USD"

    @admin.display(description="Status")
    def status_badge(self, obj) -> str:
        colour_map = {
            PaymentStatus.PENDING:   "#1565c0",
            PaymentStatus.COMPLETED: "#2e7d32",
            PaymentStatus.FAILED:    "#c62828",
            PaymentStatus.REFUNDED:  "#6d4c41",
        }
        colour = colour_map.get(obj.status, "#616161")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:3px;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    def changelist_view(self, request: HttpRequest, extra_context=None):
        """Inject revenue summary into the changelist context."""
        extra_context = extra_context or {}
        today = timezone.now().date()
        month_start = today.replace(day=1)

        total_completed = Payment.objects.filter(status=PaymentStatus.COMPLETED)

        revenue_month = (
            total_completed.filter(
                created_at__gte=timezone.make_aware(
                    timezone.datetime(month_start.year, month_start.month, 1)
                )
            ).aggregate(total=Sum("amount_usd"))["total"]
            or Decimal("0.00")
        )
        revenue_all = (
            total_completed.aggregate(total=Sum("amount_usd"))["total"]
            or Decimal("0.00")
        )
        active_count = Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            current_period_end__gte=today,
        ).count()

        extra_context["revenue_summary"] = {
            "active_subscribers": active_count,
            "revenue_month_usd":  f"${revenue_month:.2f}",
            "revenue_all_usd":    f"${revenue_all:.2f}",
            "month_label":        month_start.strftime("%B %Y"),
        }
        return super().changelist_view(request, extra_context=extra_context)
