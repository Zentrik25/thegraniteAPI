"""
tasks.py — Celery tasks for the subscriptions app.

Task inventory:
  check_expired_subscriptions()     — daily: mark overdue ACTIVE subscriptions EXPIRED
  send_renewal_reminder(sub_id)     — email reader 3 days before period end (stub)
  process_paynow_callback(payment_id) — poll Paynow and activate subscription on success
"""

import logging
from datetime import date, timedelta

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger("subscriptions.tasks")


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=True)
def check_expired_subscriptions(self) -> None:
    """
    Mark overdue ACTIVE subscriptions as EXPIRED.

    Runs daily (scheduled via Celery Beat). Selects all ACTIVE subscriptions
    whose current_period_end is in the past and transitions them to EXPIRED.

    Also handles cancel_at_period_end subscriptions whose period has ended.
    """
    from subscriptions.models import Subscription, SubscriptionStatus

    today = date.today()

    # Expire overdue active subscriptions
    expired_qs = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        current_period_end__lt=today,
    )
    expired_count = expired_qs.count()
    if expired_count:
        expired_qs.update(status=SubscriptionStatus.EXPIRED)
        logger.info(
            "[check_expired_subscriptions] Marked %d subscription(s) as EXPIRED.",
            expired_count,
        )
    else:
        logger.info("[check_expired_subscriptions] No expired subscriptions found.")

    # Finalise cancel_at_period_end subscriptions whose period has ended
    from django.utils import timezone as tz

    cancel_qs = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        cancel_at_period_end=True,
        current_period_end__lt=today,
    )
    cancel_count = cancel_qs.count()
    if cancel_count:
        cancel_qs.update(
            status=SubscriptionStatus.CANCELLED,
        )
        logger.info(
            "[check_expired_subscriptions] Finalised %d cancel_at_period_end subscription(s).",
            cancel_count,
        )

    # Invalidate affected reader caches — broad flush for now
    # (production would target specific reader IDs)
    logger.info("[check_expired_subscriptions] Task complete.")


@shared_task(bind=True, max_retries=3, default_retry_delay=120, ignore_result=True)
def send_renewal_reminder(self, subscription_id: str) -> None:
    """
    Send a renewal reminder email 3 days before the subscription period ends.

    Args:
        subscription_id: UUID string of the Subscription record.

    Stub implementation — logs instead of sending email.
    Replace with real email logic (SendGrid / Mailgun / SES) when ready.
    """
    from subscriptions.models import Subscription

    try:
        subscription = Subscription.objects.select_related("reader", "plan").get(
            id=subscription_id
        )
    except Subscription.DoesNotExist:
        logger.warning(
            "[send_renewal_reminder] Subscription %s not found — skipping.",
            subscription_id,
        )
        return

    days_left = (subscription.current_period_end - date.today()).days
    plan_name = subscription.plan.name if subscription.plan else "Unknown"
    price_usd = subscription.plan.price_usd if subscription.plan else "0.00"

    logger.info(
        "[STUB] Renewal reminder → %s  plan=%s  days_left=%d  amount_usd=$%.2f  "
        "period_end=%s",
        subscription.reader.email,
        plan_name,
        days_left,
        float(price_usd),
        subscription.current_period_end,
    )

    # TODO: Replace stub with actual email delivery:
    # send_mail(
    #     subject=f"Your Granite Post subscription renews in {days_left} days",
    #     message=f"Your {plan_name} plan (${price_usd} USD) renews on "
    #             f"{subscription.current_period_end}.",
    #     from_email="noreply@thegranite.co.zw",
    #     recipient_list=[subscription.reader.email],
    # )


@shared_task(bind=True, max_retries=5, default_retry_delay=30, ignore_result=True)
def process_paynow_callback(self, payment_id: str) -> None:
    """
    Poll Paynow for payment status and activate the subscription on success.

    Called from the PaynowCallbackView after Paynow POSTs to the result URL.
    Retries up to 5 times with 30-second delays to handle Paynow polling delays.

    Args:
        payment_id: UUID string of the Payment record to process.
    """
    from subscriptions.models import Payment, PaymentStatus, Subscription, SubscriptionStatus
    from subscriptions.paynow_client import PaynowClient

    try:
        payment = Payment.objects.select_related("subscription__reader", "subscription__plan").get(
            id=payment_id
        )
    except Payment.DoesNotExist:
        logger.warning(
            "[process_paynow_callback] Payment %s not found — skipping.",
            payment_id,
        )
        return

    if payment.status == PaymentStatus.COMPLETED:
        logger.info(
            "[process_paynow_callback] Payment %s already COMPLETED — skipping.",
            payment_id,
        )
        return

    if not payment.paynow_poll_url:
        logger.warning(
            "[process_paynow_callback] Payment %s has no poll URL — cannot confirm.",
            payment_id,
        )
        return

    client = PaynowClient()
    result = client.check_payment_status(payment.paynow_poll_url)

    if not result["ok"]:
        logger.error(
            "[process_paynow_callback] Paynow poll failed: payment=%s error=%s",
            payment_id,
            result["error"],
        )
        raise self.retry(exc=Exception(result["error"]))

    if result["paid"]:
        payment.status = PaymentStatus.COMPLETED
        payment.save(update_fields=["status", "updated_at"])

        subscription = payment.subscription
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.paynow_reference = payment.paynow_reference
        subscription.save(update_fields=["status", "paynow_reference", "updated_at"])

        # Invalidate cached subscription status for this reader
        reader_id = subscription.reader_id
        cache_key  = f"subscriptions:reader:{reader_id}:status"
        cache.delete(cache_key)

        logger.info(
            "[process_paynow_callback] Subscription activated: sub=%s payment=%s reader=%s",
            subscription.id,
            payment_id,
            subscription.reader.email,
        )
    else:
        logger.info(
            "[process_paynow_callback] Payment %s not yet confirmed by Paynow (status=%s).",
            payment_id,
            result.get("status", "unknown"),
        )
        # Retry — Paynow may confirm within the next poll window
        raise self.retry(exc=Exception("Payment not yet confirmed."))
