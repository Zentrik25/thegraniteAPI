"""
tasks.py — Celery tasks for the subscriptions app.

Task inventory:
  check_expired_subscriptions()     — daily: mark overdue ACTIVE subscriptions EXPIRED
  queue_renewal_reminders()         — daily: enqueue reminder tasks for subscriptions ending soon
  send_renewal_reminder(sub_id)     — email reader 3 days before period end
  process_paynow_callback(payment_id) — poll Paynow and activate subscription on success
"""

import logging
from datetime import date, timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail

from core.logging_utils import _mask_email

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


def _subscription_portal_url() -> str:
    """Return the frontend location readers can use to manage subscriptions."""
    return getattr(
        settings,
        "FRONTEND_URL",
        getattr(settings, "SITE_URL", ""),
    ).rstrip("/")


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
        cancel_at_period_end=False,
        current_period_end__lt=today,
    )
    expired_reader_ids = list(expired_qs.values_list("reader_id", flat=True))

    # Expire overdue active subscriptions that were NOT flagged for graceful
    # cancellation.  The cancel_at_period_end=False guard makes this correct
    # regardless of execution order — the filter itself enforces the invariant.
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
    """
    from subscriptions.models import Subscription, SubscriptionStatus

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

    if (
        subscription.status != SubscriptionStatus.ACTIVE
        or subscription.cancel_at_period_end
    ):
        logger.info(
            "[send_renewal_reminder] Subscription %s no longer eligible — skipping.",
            subscription_id,
        )
        return

    days_left = (subscription.current_period_end - date.today()).days
    plan_name = subscription.plan.name if subscription.plan else "Unknown"
    price_usd = subscription.plan.price_usd if subscription.plan else 0
    portal_url = _subscription_portal_url()

    message_lines = [
        f"Your Granite Post {plan_name} subscription renews in {days_left} day(s).",
        "",
        f"Renewal date: {subscription.current_period_end}",
        f"Amount: ${price_usd} USD",
    ]
    if portal_url:
        message_lines.extend(
            [
                "",
                "You can review your subscription here:",
                portal_url,
            ]
        )

    try:
        send_mail(
            subject=f"Your Granite Post subscription renews in {days_left} days",
            message="\n".join(message_lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[subscription.reader.email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[send_renewal_reminder] Failed: subscription=%s email=%s error=%s",
            subscription_id,
            _mask_email(subscription.reader.email),
            exc,
        )
        raise self.retry(exc=exc)

    logger.info(
        "[send_renewal_reminder] Sent: subscription=%s email=%s plan=%s days_left=%d",
        subscription_id,
        _mask_email(subscription.reader.email),
        plan_name,
        days_left,
    )


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
