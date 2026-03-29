import logging

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

        from .tasks import send_breaking_news_push
        send_breaking_news_push.apply_async(
            args=[instance.pk],
            queue="slow",
        )
        logger.info(
            "Breaking news notification queued: article pk=%s slug=%s",
            instance.pk,
            instance.slug,
        )
    except Exception as exc:
        logger.error(
            "Failed to queue breaking news notification for article pk=%s: %s",
            instance.pk,
            exc,
        )