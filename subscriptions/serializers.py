"""
serializers.py — DRF serializers for the subscriptions app.

Serializer inventory:
  SubscriptionPlanSerializer  — public read-only plan listing (USD prices)
  SubscriptionSerializer      — reader's current subscription status
  SubscribeSerializer         — input for starting a new subscription
  CancelSubscriptionSerializer— input for cancelling a subscription
  PaymentSerializer           — read-only payment history record (USD)
  PaynowCallbackSerializer    — input validation for Paynow webhook POST
  RevenueReportSerializer     — staff revenue summary (USD only)
"""

from decimal import Decimal
from urllib.parse import urlparse

from rest_framework import serializers

from .models import (
    ArticleAccess,
    BillingPeriod,
    Payment,
    PaymentMethod,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)


# ---------------------------------------------------------------------------
# Public — plan listing
# ---------------------------------------------------------------------------

class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """
    Public serializer for subscription plan listing.

    Exposes only the fields needed by the pricing page. Prices are
    always in USD. Never exposes internal admin-only fields.
    """

    price_usd           = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    billing_period_label = serializers.CharField(source="get_billing_period_display", read_only=True)
    article_access_label = serializers.CharField(source="get_article_access_display", read_only=True)

    class Meta:
        model  = SubscriptionPlan
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "price_usd",
            "billing_period",
            "billing_period_label",
            "features",
            "article_access",
            "article_access_label",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Reader — subscription status
# ---------------------------------------------------------------------------

class SubscriptionSerializer(serializers.ModelSerializer):
    """
    Serializer for a reader's current subscription.

    Exposes is_active_subscription and days_remaining properties alongside
    the plan detail so the frontend can render paywall state accurately.
    All USD amounts come from the nested plan.
    """

    plan                  = SubscriptionPlanSerializer(read_only=True)
    is_active_subscription = serializers.BooleanField(read_only=True)
    days_remaining        = serializers.IntegerField(read_only=True)
    status_label          = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model  = Subscription
        fields = [
            "id",
            "plan",
            "status",
            "status_label",
            "started_at",
            "current_period_start",
            "current_period_end",
            "cancelled_at",
            "cancel_at_period_end",
            "is_active_subscription",
            "days_remaining",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Reader — subscribe input
# ---------------------------------------------------------------------------

class SubscribeSerializer(serializers.Serializer):
    """
    Input serializer for POST /api/v1/subscriptions/subscribe/.

    Validates plan slug and payment method. Phone number is required for
    EcoCash and OneMoney; it is ignored for bank card payments.
    """

    plan_slug      = serializers.SlugField()
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    phone_number   = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        help_text="Required for EcoCash and OneMoney payments.",
    )

    def validate(self, attrs: dict) -> dict:
        """Cross-field validation: phone required for mobile payments."""
        method = attrs.get("payment_method", "")
        phone  = attrs.get("phone_number", "")

        if method in (PaymentMethod.ECOCASH, PaymentMethod.ONEMONEY) and not phone:
            raise serializers.ValidationError(
                {"phone_number": "Phone number is required for EcoCash and OneMoney payments."}
            )
        return attrs

    def validate_plan_slug(self, value: str) -> str:
        """Ensure the plan exists and is active."""
        if not SubscriptionPlan.objects.filter(slug=value, is_active=True).exists():
            raise serializers.ValidationError("Plan not found or is no longer available.")
        return value


# ---------------------------------------------------------------------------
# Reader — cancel input
# ---------------------------------------------------------------------------

class CancelSubscriptionSerializer(serializers.Serializer):
    """
    Input serializer for POST /api/v1/subscriptions/cancel/.

    cancel_immediately: if True, mark CANCELLED now; if False (default)
    set cancel_at_period_end=True and let it expire naturally.
    """

    cancel_immediately = serializers.BooleanField(default=False)


# ---------------------------------------------------------------------------
# Reader — payment history
# ---------------------------------------------------------------------------

class PaymentSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for payment history.

    amount_usd is always in USD. currency is always "USD".
    Never exposes internal Paynow poll URLs in the list (only the public
    status endpoint is used for polling).
    """

    payment_method_label = serializers.CharField(source="get_payment_method_display", read_only=True)
    status_label         = serializers.CharField(source="get_status_display", read_only=True)
    amount_usd           = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)

    class Meta:
        model  = Payment
        fields = [
            "id",
            "amount_usd",
            "currency",
            "payment_method",
            "payment_method_label",
            "status",
            "status_label",
            "paynow_reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Paynow webhook input
# ---------------------------------------------------------------------------

class PaynowCallbackSerializer(serializers.Serializer):
    """
    Input validation for Paynow result URL webhook.

    Paynow POSTs form-encoded data to the result URL. Only the fields
    we act on are declared here; extras are silently ignored.
    """

    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    paynowreference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    status    = serializers.CharField(max_length=50)
    pollurl   = serializers.CharField(max_length=500, required=False, allow_blank=True)
    amount    = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
    )

    def validate(self, attrs: dict) -> dict:
        """Reject malformed callback bodies before they reach task dispatch."""
        reference = (attrs.get("reference") or "").strip()
        paynowreference = (attrs.get("paynowreference") or "").strip()
        status_value = (attrs.get("status") or "").strip()
        pollurl = (attrs.get("pollurl") or "").strip()
        amount = attrs.get("amount", Decimal("0.00"))

        if not reference and not paynowreference:
            raise serializers.ValidationError(
                {"reference": "reference or paynowreference is required."}
            )

        if not status_value:
            raise serializers.ValidationError({"status": "This field may not be blank."})

        if amount < 0:
            raise serializers.ValidationError({"amount": "Amount cannot be negative."})

        if pollurl:
            parsed = urlparse(pollurl)
            if parsed.scheme != "https" or not parsed.netloc.endswith("paynow.co.zw"):
                raise serializers.ValidationError(
                    {"pollurl": "Must be a valid Paynow poll URL."}
                )

        attrs["reference"] = reference
        attrs["paynowreference"] = paynowreference
        attrs["status"] = status_value
        attrs["pollurl"] = pollurl
        return attrs


# ---------------------------------------------------------------------------
# Staff — all subscriptions
# ---------------------------------------------------------------------------

class SubscriptionListSerializer(serializers.ModelSerializer):
    """
    Staff-only serializer for the all-subscriptions list.

    Includes reader email and plan name for quick scanning.
    """

    reader_email           = serializers.EmailField(source="reader.email", read_only=True)
    reader_username        = serializers.CharField(source="reader.username", read_only=True)
    plan_name              = serializers.CharField(source="plan.name", read_only=True, default="")
    plan_price_usd         = serializers.DecimalField(
        source="plan.price_usd",
        max_digits=6,
        decimal_places=2,
        read_only=True,
        default=Decimal("0.00"),
    )
    is_active_subscription  = serializers.BooleanField(read_only=True)
    days_remaining          = serializers.IntegerField(read_only=True)
    status_label            = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model  = Subscription
        fields = [
            "id",
            "reader_email",
            "reader_username",
            "plan_name",
            "plan_price_usd",
            "status",
            "status_label",
            "started_at",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "is_active_subscription",
            "days_remaining",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Staff — revenue report
# ---------------------------------------------------------------------------

class RevenueReportSerializer(serializers.Serializer):
    """
    Staff revenue summary.

    All monetary values are in USD only. This serializer is write-only
    (used to return data from the view, not to accept input).
    """

    total_active_subscribers  = serializers.IntegerField()
    total_revenue_usd_month   = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_revenue_usd_all_time = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency                  = serializers.CharField(default="USD")
    report_month              = serializers.CharField()
    breakdown_by_plan         = serializers.ListField(child=serializers.DictField())
