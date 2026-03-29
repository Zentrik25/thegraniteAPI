"""
signals.py — Django signals for The Granite Post articles app.

Handles side effects that must not live in model.save():
  - Enforce one article per top story rank slot before the DB constraint fires.
    This covers direct ORM saves from management commands, tests, and fixtures
    in addition to the admin save_model override.
  - Log status transitions for the audit trail.

Connected in apps.py via AppConfig.ready().
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger("articles.signals")


@receiver(pre_save, sender="articles.Article")
def enforce_unique_top_story_rank(sender, instance, **kwargs):
    """
    Before saving an article with top_story_rank set, displace any other
    article currently occupying that rank by setting its rank to NULL.

    This runs for every ORM save path — admin, shell, management commands,
    and test factories — so the UniqueConstraint in Meta never trips.
    """
    if instance.top_story_rank is None:
        return

    displaced = (
        sender.objects
        .filter(top_story_rank=instance.top_story_rank)
        .exclude(pk=instance.pk)
    )
    if displaced.exists():
        count = displaced.update(top_story_rank=None, is_top_story=False, updated_at=timezone.now())
        logger.info(
            "enforce_unique_top_story_rank: cleared rank %d from %d article(s) "
            "to assign it to pk=%s ('%s').",
            instance.top_story_rank,
            count,
            instance.pk or "NEW",
            instance.title,
        )


@receiver(pre_save, sender="articles.Article")
def log_status_transition(sender, instance, **kwargs):
    """
    Log whenever an existing article's status changes.
    Skips brand-new articles (pk is None) as there is no prior state.
    """
    if instance.pk is None:
        return

    try:
        previous = sender.objects.only("status").get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    if previous.status != instance.status:
        logger.info(
            "Article pk=%s '%s': status %s → %s.",
            instance.pk,
            instance.title,
            previous.status,
            instance.status,
        )


@receiver(post_save, sender="articles.Article")
def purge_cloudflare_on_publish(sender, instance, **kwargs) -> None:
    """
    Purge Cloudflare CDN cache when an article is published or updated.

    Only fires for published articles — drafts and review items are not
    publicly cached so there is nothing to purge.
    Silently skips when Cloudflare credentials are not configured (dev/test).
    """
    if instance.status != "published":
        return

    try:
        from core.cloudflare_purge import purge_article_cache
        purge_article_cache(instance.slug)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Cloudflare purge failed for article pk=%s slug=%s: %s",
            instance.pk,
            instance.slug,
            exc,
        )
