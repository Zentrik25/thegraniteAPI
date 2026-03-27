import logging

from django.core.cache import cache
from django.db import models

logger = logging.getLogger("core.models")


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CachedModel(TimeStampedModel):
    CACHE_KEYS: list[str] = []

    class Meta:
        abstract = True

    def get_cache_keys(self) -> list[str]:
        resolved = []
        for pattern in self.CACHE_KEYS:
            try:
                resolved.append(pattern.format(**self.__dict__))
            except (KeyError, AttributeError):
                resolved.append(pattern)
        return resolved

    def invalidate_cache(self) -> None:
        keys = self.get_cache_keys()
        if not keys:
            return
        cache.delete_many(keys)
        logger.debug(
            "%s pk=%s: invalidated %d cache key(s).",
            self.__class__.__name__,
            self.pk or "NEW",
            len(keys),
        )

    def save(self, *args, **kwargs) -> None:
        super().save(*args, **kwargs)
        self.invalidate_cache()

    def delete(self, *args, **kwargs):
        self.invalidate_cache()
        return super().delete(*args, **kwargs)
