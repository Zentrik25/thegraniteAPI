import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("sections.signals")


@receiver(post_save, sender="sections.Section")
def invalidate_section_cache(sender, instance, **kwargs) -> None:
    try:
        from django.core.cache import cache
        from core.cache import make_cache_key

        keys = [
            make_cache_key("sections:list"),
            make_cache_key("sections:list:primary"),
            make_cache_key("sections:list:secondary"),
            make_cache_key(f"sections:detail:{instance.slug}"),
            make_cache_key(f"sections:articles:{instance.slug}"),
        ]
        cache.delete_many(keys)
        logger.debug(
            "Section cache cleared: pk=%s slug=%s",
            instance.pk,
            instance.slug,
        )
    except Exception as exc:
        logger.error("Failed to clear section cache: %s", exc)