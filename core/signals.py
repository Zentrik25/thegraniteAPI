import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger("core.signals")


@receiver(post_save, sender="articles.Article")
def on_article_save(sender, instance, created, **kwargs) -> None:
    from core.tasks import invalidate_article_cache, ping_sitemaps

    if instance.slug:
        invalidate_article_cache.apply_async(
            args=[instance.slug],
            queue="fast",
        )

    if (
        not created
        and instance.status == "published"
        and instance.published_at is not None
    ):
        ping_sitemaps.apply_async(queue="slow")
        logger.info(
            "Queued sitemap ping after publish: article pk=%s slug=%s.",
            instance.pk,
            instance.slug,
        )


@receiver(post_delete, sender="articles.Article")
def on_article_delete(sender, instance, **kwargs) -> None:
    from core.tasks import invalidate_article_cache

    if instance.slug:
        invalidate_article_cache.apply_async(
            args=[instance.slug],
            queue="fast",
        )


@receiver(post_save, sender="articles.Category")
def on_category_save(sender, instance, **kwargs) -> None:
    from core.tasks import invalidate_category_cache

    if instance.slug:
        invalidate_category_cache.apply_async(
            args=[instance.slug],
            queue="fast",
        )
