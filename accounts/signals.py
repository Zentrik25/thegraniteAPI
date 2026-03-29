"""
signals.py — Cache invalidation signals for reader accounts.

Post-save and post-delete signals on Bookmark and ReadingHistory clear
the per-reader cache keys so that API responses always reflect current state
without waiting for TTL expiry.
"""

import logging

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger("accounts.signals")


@receiver([post_save, post_delete], sender="accounts.Bookmark")
def invalidate_bookmark_cache(sender, instance, **kwargs) -> None:
    """Clear the cached bookmark count for the affected reader."""
    key = f"accounts:bookmarks:count:{instance.reader_id}"
    cache.delete(key)
    logger.debug("Invalidated bookmark cache: reader_id=%s", instance.reader_id)


@receiver([post_save, post_delete], sender="accounts.ReadingHistory")
def invalidate_history_cache(sender, instance, **kwargs) -> None:
    """Clear the cached reading history for the affected reader."""
    key = f"accounts:history:{instance.reader_id}"
    cache.delete(key)
    logger.debug("Invalidated history cache: reader_id=%s", instance.reader_id)
