import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("notifications.signals")


@receiver(post_save, sender="articles.Article")
def send_breaking_news_notification(sender, instance, created, **kwargs) -> None:
    """
    Send a push notification when an article is marked as breaking news.

    Only fires when:
    1. The article is published
    2. is_breaking is True
    3. The article was not already breaking (prevents duplicate sends
       on every subsequent save)
    """
    if not instance.is_breaking:
        return

    if instance.status != "published":
        return

    try:
        # Check if this article was already breaking before this save.
        # If it was, do not send again.
        from articles.models import Article
        try:
            old = Article.objects.get(pk=instance.pk)
            if old.is_breaking and not created:
                # Already was breaking — do not send duplicate.
                return
        except Article.DoesNotExist:
            pass

        # Web push makes external HTTP calls.  Defer until after the DB
        # transaction commits so a rolled-back save never fires a push, and
        # the request thread is not held waiting on external latency.
        # In TestCase tests the transaction never commits, so this is a
        # no-op there — which prevents real push calls during test runs.
        pk   = instance.pk
        slug = instance.slug

        def _push():
            from .tasks import send_breaking_news_push
            send_breaking_news_push.apply_async(args=[pk], queue="slow")
            logger.info(
                "Breaking news notification queued: article pk=%s slug=%s",
                pk,
                slug,
            )

        transaction.on_commit(_push)

    except Exception as exc:
        logger.error(
            "Failed to queue breaking news notification for article pk=%s: %s",
            instance.pk,
            exc,
        )