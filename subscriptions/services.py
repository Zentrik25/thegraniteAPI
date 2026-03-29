"""
services.py — Subscription activation service.

Provides a single safe function to activate a subscription after Paynow
confirms payment. Both the poll endpoint and the async callback task call
this function — never the old inline helper — ensuring identical behaviour
under concurrent access.
"""

import logging
from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Case, IntegerField, Value, When
from django.db import transaction

logger = logging.getLogger("subscriptions.services")

# Tolerate ±$0.01 rounding differences in Paynow reported amounts.
_AMOUNT_TOLERANCE = Decimal("0.01")


def get_effective_subscription(reader):
    """
    Return the subscription that should count as "current" for a reader.

    Ranking:
      1. ACTIVE subscriptions whose billing period has not ended
      2. TRIALING subscriptions awaiting payment confirmation
      3. Any remaining historical rows, newest first
    """
    from subscriptions.models import Subscription, SubscriptionStatus

    today = date.today()
    return (
        Subscription.objects.filter(reader=reader)
        .select_related("plan")
        .annotate(
            effective_rank=Case(
                When(
                    status=SubscriptionStatus.ACTIVE,
                    current_period_end__gte=today,
                    then=Value(0),
                ),
                When(status=SubscriptionStatus.TRIALING, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("effective_rank", "-current_period_end", "-created_at")
        .first()
    )


def activate_subscription(
    payment_id: str,
    reported_amount: float,
    reported_reference: str = "",
) -> bool:
    """
    Atomically activate a subscription once Paynow confirms payment.

    Safety guarantees
    -----------------
    Idempotent  — returns False immediately if the payment is already COMPLETED
                  so duplicate calls from the poll endpoint and callback task are
                  silently dropped.
    Row-locked  — SELECT FOR UPDATE closes the race window between two concurrent
                  callers (e.g. Paynow callback arriving while the reader is
                  actively polling) both seeing ``paid=True`` simultaneously.
    Atomic      — the payment write and subscription write share a single DB
                  transaction; a crash between them can never leave the reader
                  in a paid-but-no-access limbo.
    Amount-check — rejects activation when Paynow's reported amount differs from
                  the expected amount by more than $0.01 (fraud / mis-config guard).

    Args:
        payment_id:      UUID string of the Payment record to activate.
        reported_amount: Amount (USD) as confirmed by Paynow's poll response.
        reported_reference: Paynow reference returned by the status poll/callback.

    Returns:
        True  — activation completed; payment is now COMPLETED, subscription ACTIVE.
        False — already activated (idempotent no-op) or amount mismatch (rejected).

    Raises:
        Payment.DoesNotExist — propagated to caller when payment_id is unknown.
    """
    from subscriptions.models import Payment, PaymentStatus, SubscriptionStatus

    with transaction.atomic():
        # Lock the row before reading status to eliminate the TOCTOU race
        # between two concurrent activation attempts.
        payment = (
            Payment.objects.select_related("subscription__reader")
            .select_for_update()
            .get(id=payment_id)
        )

        # Idempotency guard — a previous call already completed this payment.
        if payment.status == PaymentStatus.COMPLETED:
            logger.info(
                "[activate_subscription] Payment %s already COMPLETED — skipping.",
                payment_id,
            )
            return False

        # Reference verification — refuse if Paynow reports a different payment.
        if reported_reference and payment.paynow_reference:
            if reported_reference != payment.paynow_reference:
                logger.error(
                    "[activate_subscription] REFERENCE MISMATCH for payment %s - "
                    "activation refused.",
                    payment_id,
                )
                return False

        # Amount verification — refuse if Paynow reports a different figure.
        try:
            reported = Decimal(str(reported_amount))
        except Exception:
            reported = Decimal("0")

        if abs(reported - payment.amount_usd) > _AMOUNT_TOLERANCE:
            logger.error(
                "[activate_subscription] AMOUNT MISMATCH for payment %s: "
                "expected=%s reported=%s — activation refused.",
                payment_id,
                payment.amount_usd,
                reported_amount,
            )
            return False

        # All checks passed — write both rows atomically.
        payment.status = PaymentStatus.COMPLETED
        payment.save(update_fields=["status", "updated_at"])

        subscription = payment.subscription
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.paynow_reference = payment.paynow_reference
        subscription.save(update_fields=["status", "paynow_reference", "updated_at"])

    # Cache invalidation is intentionally outside the transaction so we do not
    # hold the row lock while talking to Redis.
    cache.delete(f"subscriptions:reader:{subscription.reader_id}:status")

    logger.info(
        "[activate_subscription] Subscription activated: sub=%s payment=%s reader_id=%s",
        subscription.id,
        payment_id,
        subscription.reader_id,
    )
    return True
