import json
import logging

from celery import shared_task

logger = logging.getLogger("notifications.tasks")

# Maximum subscriptions processed per Celery task.
# Keeps individual tasks short and lets Celery workers process batches in
# parallel instead of one worker blocking on thousands of serial HTTP calls.
_FANOUT_BATCH_SIZE = 100


@shared_task(
    queue="slow",
    ignore_result=True,
    name="notifications.tasks.send_breaking_news_push",
)
def send_breaking_news_push(article_pk: int) -> None:
    """
    Send a push notification to all active subscribers for a breaking article.

    Called automatically when an article is marked as breaking.
    Runs asynchronously via Celery so it does not block the request.

    Failed subscriptions (410 Gone) are automatically deactivated.
    """
    from articles.models import Article
    from .models import Notification, PushSubscription

    try:
        article = Article.objects.get(pk=article_pk)
    except Article.DoesNotExist:
        logger.error("Article pk=%s not found for push notification.", article_pk)
        return

    subscriptions = PushSubscription.objects.filter(is_active=True)
    total         = subscriptions.count()

    if total == 0:
        logger.info("No active push subscriptions — skipping notification.")
        return

    title   = f"BREAKING: {article.title}"
    body    = article.excerpt or article.title
    url     = f"/articles/{article.slug}/"
    icon    = article.image_url or ""

    payload = json.dumps({
        "title":   title,
        "body":    body,
        "url":     url,
        "icon":    icon,
        "badge":   "/static/icons/badge.png",
        "tag":     f"breaking-{article.pk}",
        "renotify": True,
    })

    notification = Notification.objects.create(
        article    = article,
        title      = title,
        body       = body,
        url        = url,
        icon_url   = icon,
        sent_count = total,
    )

    # Dispatch batches in parallel instead of a serial loop so that thousands
    # of HTTP calls don't block a single worker for minutes.
    sub_pks = list(subscriptions.values_list("pk", flat=True))
    batch_count = 0
    for i in range(0, len(sub_pks), _FANOUT_BATCH_SIZE):
        batch = sub_pks[i : i + _FANOUT_BATCH_SIZE]
        _send_push_batch.apply_async(
            args=[notification.pk, batch],
            queue="slow",
        )
        batch_count += 1

    logger.info(
        "Push notification queued: article=%s total=%d batches=%d",
        article.slug,
        total,
        batch_count,
    )


@shared_task(
    queue="slow",
    ignore_result=True,
    name="notifications.tasks._send_push_batch",
)
def _send_push_batch(notification_pk: int, subscription_pks: list) -> None:
    """
    Send push notifications to a batch of subscriptions.

    Called exclusively by send_breaking_news_push to parallelise the fanout.
    Each batch processes up to _FANOUT_BATCH_SIZE subscriptions so workers run
    concurrently rather than one worker blocking on the full list.

    Deactivates any subscriptions that return 410 Gone.
    """
    from .models import Notification, PushSubscription

    try:
        notification = Notification.objects.get(pk=notification_pk)
    except Notification.DoesNotExist:
        logger.error("_send_push_batch: Notification pk=%s not found.", notification_pk)
        return

    payload = json.dumps({
        "title":    notification.title,
        "body":     notification.body,
        "url":      notification.url,
        "icon":     notification.icon_url,
        "badge":    "/static/icons/badge.png",
        "tag":      f"breaking-{notification.article_id}",
        "renotify": True,
    })

    subscriptions = PushSubscription.objects.filter(
        pk__in=subscription_pks, is_active=True
    )

    success_count = 0
    failed_count  = 0
    to_deactivate = []

    for subscription in subscriptions:
        result = _send_push(subscription, payload)
        if result == "success":
            success_count += 1
        elif result == "gone":
            to_deactivate.append(subscription.pk)
            failed_count += 1
        else:
            failed_count += 1

    if to_deactivate:
        PushSubscription.objects.filter(pk__in=to_deactivate).update(is_active=False)
        logger.info(
            "_send_push_batch: deactivated %d expired subscriptions.",
            len(to_deactivate),
        )

    logger.info(
        "_send_push_batch: notification=%s success=%d failed=%d",
        notification_pk,
        success_count,
        failed_count,
    )


def _send_push(subscription, payload: str) -> str:
    """
    Send a Web Push notification to one subscription.

    Returns:
        "success"  — delivered successfully
        "gone"     — endpoint returned 410, subscription should be deleted
        "error"    — any other error
    """
    try:
        import os
        from pywebpush import webpush, WebPushException

        vapid_private_key = os.environ.get("VAPID_PRIVATE_KEY", "")
        vapid_claims_email = os.environ.get(
            "VAPID_CLAIMS_EMAIL", "editor@thegranite.co.zw"
        )

        if not vapid_private_key:
            logger.warning(
                "VAPID_PRIVATE_KEY not set — push notification skipped."
            )
            return "error"

        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth":   subscription.auth,
                },
            },
            data=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims={
                "sub": f"mailto:{vapid_claims_email}",
            },
        )

        from django.utils import timezone
        PushSubscription.objects.filter(pk=subscription.pk).update(
            last_used=timezone.now()
        )
        return "success"

    except Exception as exc:
        exc_str = str(exc)
        if "410" in exc_str or "Gone" in exc_str:
            return "gone"
        logger.error(
            "Push send error for subscription %s: %s",
            subscription.pk,
            exc,
        )
        return "error"
    
@shared_task(
    queue="slow",
    ignore_result=True,
    name="notifications.tasks.send_test_push",
)
def send_test_push() -> None:
    """Send a test push notification to all active subscribers."""
    import json
    from .models import Notification, PushSubscription

    subscriptions = PushSubscription.objects.filter(is_active=True)
    total         = subscriptions.count()

    if total == 0:
        logger.info("No active subscriptions for test push.")
        return

    payload = json.dumps({
        "title": "Test Notification — The Granite Post",
        "body":  "Push notifications are working correctly.",
        "url":   "/",
        "tag":   "test-notification",
    })

    success = 0
    failed  = 0
    gone    = []

    for sub in subscriptions:
        result = _send_push(sub, payload)
        if result == "success":
            success += 1
        elif result == "gone":
            gone.append(sub.pk)
            failed += 1
        else:
            failed += 1

    if gone:
        PushSubscription.objects.filter(pk__in=gone).update(is_active=False)

    logger.info(
        "Test push sent: total=%d success=%d failed=%d",
        total, success, failed,
    )