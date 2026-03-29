"""
tasks.py — Celery tasks for the subscriptions app.

Task inventory:
  check_expired_subscriptions()     — daily: mark overdue ACTIVE subscriptions EXPIRED
  queue_renewal_reminders()         — daily: enqueue reminder tasks for subscriptions ending soon
  send_renewal_reminder(sub_id)     — email reader 3 days before period end (stub)
  process_paynow_callback(payment_id) — poll Paynow and activate subscription on success
"""

import logging
from datetime import date, timedelta

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger("subscriptions.tasks")


def _invalidate_subscription_status_cache(reader_ids: list[str]) -> None:
    """Invalidate cached paywall status for the given reader IDs."""
    unique_reader_ids = list(dict.fromkeys(str(reader_id) for reader_id in reader_ids if reader_id))
    if not unique_reader_ids:
        return

    cache.delete_many(
        [f"subscriptions:reader:{reader_id}:status" for reader_id in unique_reader_ids]
    )
    logger.info(
        "[subscriptions.tasks] Invalidated subscription cache for %d reader(s).",
        len(unique_reader_ids),
    )


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

    cancel_qs = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        cancel_at_period_end=True,
        current_period_end__lt=today,
    )
    cancel_reader_ids = list(cancel_qs.values_list("reader_id", flat=True))

    # Process cancel_at_period_end subscriptions FIRST so they land in
    # CANCELLED rather than EXPIRED — the general sweep below would otherwise
    # grab them first and mark them EXPIRED before we can distinguish them.
    cancel_count = cancel_qs.update(status=SubscriptionStatus.CANCELLED)
    if cancel_count:
        logger.info(
            "[check_expired_subscriptions] Finalised %d cancel_at_period_end subscription(s).",
            cancel_count,
        )

    expired_qs = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        current_period_end__lt=today,
    )
    expired_reader_ids = list(expired_qs.values_list("reader_id", flat=True))

    # Expire any remaining overdue active subscriptions (those not flagged for
    # graceful cancellation above).
    expired_count = expired_qs.update(status=SubscriptionStatus.EXPIRED)
    if expired_count:
        logger.info(
            "[check_expired_subscriptions] Marked %d subscription(s) as EXPIRED.",
            expired_count,
        )
    else:
        logger.info("[check_expired_subscriptions] No expired subscriptions found.")

    _invalidate_subscription_status_cache(cancel_reader_ids + expired_reader_ids)
    logger.info("[check_expired_subscriptions] Task complete.")


@shared_task(bind=True, max_retries=3, default_retry_delay=300, ignore_result=True)
def queue_renewal_reminders(self) -> None:
    """
    Enqueue reminder tasks for active subscriptions ending in 3 days.

    This task is designed for daily Celery Beat scheduling. It keeps the
    existing send_renewal_reminder task stable and only adds the missing
    batch-selection step.
    """
    from subscriptions.models import Subscription, SubscriptionStatus

    target_date = date.today() + timedelta(days=3)
    subscription_ids = list(
        Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=False,
            current_period_end=target_date,
        ).values_list("id", flat=True)
    )

    for subscription_id in subscription_ids:
        send_renewal_reminder.delay(str(subscription_id))

    logger.info(
        "[queue_renewal_reminders] Enqueued %d reminder task(s) for %s.",
        len(subscription_ids),
        target_date,
    )


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
    from subscriptions.models import Payment, PaymentStatus
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
            "[process_paynow_callback] Paynow poll failed: payment=%s",
            payment_id,
        )
        raise self.retry(exc=Exception(result["error"]))

    if result["paid"]:
        from subscriptions.services import activate_subscription
        activated = activate_subscription(
            payment_id,
            result["amount"],
            result.get("reference", ""),
        )
        if activated:
            logger.info(
                "[process_paynow_callback] Subscription activated: payment=%s",
                payment_id,
            )
        else:
            # Either already COMPLETED (idempotent) or amount mismatch (logged
            # inside the service). Either way, do not retry.
            logger.info(
                "[process_paynow_callback] Activation skipped for payment=%s "
                "(already done or amount mismatch).",
                payment_id,
            )
    else:
        logger.info(
            "[process_paynow_callback] Payment %s not yet confirmed by Paynow (status=%s).",
            payment_id,
            result.get("status", "unknown"),
        )
        # Retry — Paynow may confirm within the next poll window.
        raise self.retry(exc=Exception("Payment not yet confirmed."))
