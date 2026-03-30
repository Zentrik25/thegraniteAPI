import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger("core.signals")


@receiver(post_save, sender="articles.Article")
def on_article_save(sender, instance, created, **kwargs) -> None:
    from core.tasks import invalidate_article_cache, ping_sitemaps

    if instance.slug:
        # Cache invalidation is idempotent and fast — run inline.
        invalidate_article_cache.apply_async(
            args=[instance.slug],
            queue="fast",
        )

    if (
        not created
        and instance.status == "published"
        and instance.published_at is not None
    ):
        # Sitemap pings make external HTTP requests.  Defer until after the
        # DB transaction commits so:
        #  (a) a rolled-back admin save does not trigger a ping, and
        #  (b) the request thread is not blocked by third-party latency.
        # In TestCase tests the enclosing transaction never commits, so this
        # callback never fires — which also stops spurious HTTP calls in CI.
        slug = instance.slug
        pk   = instance.pk

        def _ping():
            ping_sitemaps.apply_async(queue="slow")
            logger.info(
                "Queued sitemap ping after publish: article pk=%s slug=%s.",
                pk,
                slug,
            )

        transaction.on_commit(_ping)


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
