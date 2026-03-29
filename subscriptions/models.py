"""
models.py — Subscription, plan, and payment models for The Granite Post.

Model inventory:
  SubscriptionPlan  — pricing tiers with Paynow USD billing configuration
  Subscription      — a reader's active or historical subscription record
  Payment           — individual Paynow payment transactions in USD

All monetary values are stored and displayed in USD only.
"""

import uuid
from datetime import date

from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class BillingPeriod(models.TextChoices):
    """How often a subscription renews."""

    MONTHLY = "monthly", "Monthly"
    ANNUAL  = "annual",  "Annual"


class ArticleAccess(models.TextChoices):
    """
    Which articles this plan unlocks.

    FREE_ONLY — reader can only access free (is_premium=False) articles
    PREMIUM   — reader can access premium + free articles
    ALL       — full access including supporter-only content
    """

    FREE_ONLY = "free_only", "Free articles only"
    PREMIUM   = "premium",   "Premium articles"
    ALL       = "all",       "All articles (Supporter)"


class SubscriptionStatus(models.TextChoices):
    """Lifecycle states for a Subscription record."""

    ACTIVE    = "active",    "Active"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED   = "expired",   "Expired"
    PAST_DUE  = "past_due",  "Past Due"
    TRIALING  = "trialing",  "Trialing"


class PaymentMethod(models.TextChoices):
    """Paynow-supported payment channels."""

    ECOCASH       = "ecocash",        "EcoCash"
    ONEMONEY      = "onemoney",       "OneMoney"
    BANK_CARD     = "bank_card",      "Bank Card"
    BANK_TRANSFER = "bank_transfer",  "Bank Transfer"


class PaymentStatus(models.TextChoices):
    """Lifecycle states for an individual Paynow payment."""

    PENDING   = "pending",   "Pending"
    COMPLETED = "completed", "Completed"
    FAILED    = "failed",    "Failed"
    REFUNDED  = "refunded",  "Refunded"


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------

class SubscriptionPlan(models.Model):
    """
    A pricing tier available for reader subscriptions.

    Three default plans are created via data migration:
      - Free      ($0.00/month)  — free articles only
      - Premium   ($2.00/month)  — premium + free articles
      - Supporter ($5.00/month)  — all articles + supporter badge

    All prices are in USD. ZWL/ZIG are never stored or referenced.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    name = models.CharField(
        max_length=100,
        help_text="Display name, e.g. 'Basic', 'Premium', 'Supporter'.",
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="URL-safe identifier. Auto-generated; do not change after creation.",
    )
    description = models.TextField(
        blank=True,
        help_text="Short plan description shown on the pricing page.",
    )
    price_usd = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Monthly or annual price in USD. Free plans use 0.00.",
    )
    billing_period = models.CharField(
        max_length=20,
        choices=BillingPeriod.choices,
        default=BillingPeriod.MONTHLY,
        help_text="How often this plan is billed.",
    )
    features = models.JSONField(
        default=list,
        blank=True,
        help_text="List of feature strings displayed on the pricing page.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Only active plans appear on the public pricing page.",
    )
    article_access = models.CharField(
        max_length=20,
        choices=ArticleAccess.choices,
        default=ArticleAccess.FREE_ONLY,
        help_text="Which articles this plan unlocks for readers.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering     = ["price_usd"]
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"
        indexes = [
            models.Index(fields=["is_active", "price_usd"], name="plan_active_price_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (${self.price_usd}/{'mo' if self.billing_period == BillingPeriod.MONTHLY else 'yr'})"


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

class Subscription(models.Model):
    """
    A reader's subscription to a plan.

    One reader may hold multiple historical subscriptions but only one ACTIVE
    subscription at a time — enforced at the view layer.

    paynow_reference stores the transaction reference returned by Paynow so
    that payment disputes can be investigated.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    reader = models.ForeignKey(
        "accounts.ReaderAccount",
        on_delete=models.CASCADE,
        related_name="subscriptions",
        help_text="The reader who holds this subscription.",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
        help_text="The plan this subscription is on. SET_NULL on plan deletion.",
    )
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.TRIALING,
        db_index=True,
    )
    started_at = models.DateTimeField(
        default=timezone.now,
        help_text="When this subscription was first created.",
    )
    current_period_start = models.DateField(
        help_text="Start of the current billing period.",
    )
    current_period_end = models.DateField(
        help_text="End of the current billing period. Paywall checks this date.",
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the reader requested cancellation. Null if not cancelled.",
    )
    cancel_at_period_end = models.BooleanField(
        default=False,
        help_text=(
            "If True, the subscription remains active until current_period_end "
            "then transitions to CANCELLED."
        ),
    )
    paynow_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Paynow transaction reference for the most recent payment.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering     = ["-created_at"]
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        indexes = [
            models.Index(fields=["reader", "status"],              name="sub_reader_status_idx"),
            models.Index(fields=["status", "current_period_end"],  name="sub_status_period_end_idx"),
        ]

    def __str__(self) -> str:
        plan_name = self.plan.name if self.plan else "No Plan"
        return f"{self.reader} — {plan_name} ({self.status})"

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def is_active_subscription(self) -> bool:
        """True if status is ACTIVE and the current period has not expired."""
        return (
            self.status == SubscriptionStatus.ACTIVE
            and self.current_period_end >= date.today()
        )

    @property
    def days_remaining(self) -> int:
        """Number of days remaining in the current billing period."""
        return (self.current_period_end - date.today()).days


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

class Payment(models.Model):
    """
    A single Paynow payment transaction linked to a subscription.

    All amounts are in USD. EcoCash and OneMoney are mobile payments that
    require a phone_number. Bank card payments use the web redirect flow.

    paynow_poll_url is used by the frontend polling endpoint to check whether
    the payment has been confirmed by Paynow.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="payments",
        help_text="The subscription this payment is for.",
    )
    amount_usd = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Amount charged in USD.",
    )
    currency = models.CharField(
        max_length=10,
        default="USD",
        help_text="Currency code. Always USD for The Granite Post.",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    paynow_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reference string returned by Paynow on payment initiation.",
    )
    paynow_poll_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="Paynow URL to poll to check payment completion status.",
    )
    paynow_redirect_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="Paynow URL to redirect the reader to for web/card payments.",
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Reader's mobile number for EcoCash or OneMoney payments.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering     = ["-created_at"]
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        indexes = [
            models.Index(fields=["status", "created_at"],       name="payment_status_created_idx"),
            models.Index(fields=["subscription", "status"],     name="payment_sub_status_idx"),
            models.Index(fields=["paynow_reference"],           name="payment_paynow_ref_idx"),
        ]

    def __str__(self) -> str:
        return f"Payment ${self.amount_usd} USD — {self.status} ({self.payment_method})"
