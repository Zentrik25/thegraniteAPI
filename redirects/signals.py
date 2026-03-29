import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

logger = logging.getLogger("redirects.signals")


@receiver(pre_save, sender="articles.Article")
def create_redirect_on_slug_change(sender, instance, **kwargs) -> None:
    """
    Automatically create a 301 redirect when an Article slug changes.

    Uses pre_save so we can compare the old slug (from DB) with the
    new slug (on the instance) before the save happens.

    Redirect chain resolution
    -------------------------
    If old-slug already has a redirect pointing to it we update
    that redirect to point to new-slug directly preventing chains.

    Example:
      very-old-slug → old-slug  (existing redirect)
      old-slug changes to new-slug

    After resolution:
      very-old-slug → new-slug  (updated)
      old-slug      → new-slug  (new)
    """
    if not instance.pk:
        return

    try:
        old_instance = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    old_slug = old_instance.slug
    new_slug = instance.slug

    if not old_slug or not new_slug or old_slug == new_slug:
        return

    old_path = f"/articles/{old_slug}/"
    new_path = f"/articles/{new_slug}/"

    try:
        from .models import Redirect

        # Resolve redirect chains.
        chain_count = Redirect.objects.filter(new_path=old_path).update(
            new_path=new_path
        )
        if chain_count:
            logger.info(
                "Redirect chain resolved: %d redirect(s) updated from %s to %s",
                chain_count,
                old_path,
                new_path,
            )

        # Create or update the redirect.
        redirect, created = Redirect.objects.update_or_create(
            old_path = old_path,
            defaults = {
                "new_path":   new_path,
                "is_active":  True,
                "created_by": "signal",
                "note": (
                    f"Auto-created: article pk={instance.pk} "
                    f"slug changed from '{old_slug}' to '{new_slug}'"
                ),
            },
        )

        action = "created" if created else "updated"
        logger.info(
            "Redirect %s: %s → %s (article pk=%s)",
            action,
            old_path,
            new_path,
            instance.pk,
        )

        _clear_redirect_cache(old_path)

    except Exception as exc:
        logger.error(
            "Failed to create redirect for article pk=%s: %s",
            instance.pk,
            exc,
        )


def _clear_redirect_cache(old_path: str) -> None:
    try:
        from django.core.cache import cache
        from core.cache import make_cache_key
        cache.delete(make_cache_key(f"redirect:{old_path}"))
    except Exception:
        pass