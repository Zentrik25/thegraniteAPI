import logging

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import AdCampaign, Advertiser, AdZone, make_zone_cache_key

logger = logging.getLogger("advertising.signals")


def _invalidate_zone_cache_by_ids(zone_ids) -> None:
    if not zone_ids:
        return

    slugs = (
        AdZone.objects
        .filter(pk__in={zone_id for zone_id in zone_ids if zone_id})
        .values_list("slug", flat=True)
    )

    for slug in slugs:
        cache.delete(make_zone_cache_key(slug))
        logger.debug("Zone cache invalidated: slug=%s", slug)


@receiver(pre_save, sender=AdCampaign)
def remember_previous_campaign_zone(sender, instance, **kwargs) -> None:
    if instance.pk is None:
        return
    try:
        previous = sender.objects.only("zone_id").get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    instance._previous_zone_id = previous.zone_id


@receiver(post_save, sender=AdCampaign)
def invalidate_campaign_zone_cache_on_save(sender, instance, **kwargs) -> None:
    _invalidate_zone_cache_by_ids({
        instance.zone_id,
        getattr(instance, "_previous_zone_id", None),
    })


@receiver(post_delete, sender=AdCampaign)
def invalidate_campaign_zone_cache_on_delete(sender, instance, **kwargs) -> None:
    _invalidate_zone_cache_by_ids({instance.zone_id})


@receiver(post_save, sender=AdZone)
def invalidate_zone_cache_on_save(sender, instance, **kwargs) -> None:
    cache.delete(make_zone_cache_key(instance.slug))
    logger.debug("Zone cache invalidated on save: slug=%s", instance.slug)


@receiver(post_delete, sender=AdZone)
def invalidate_zone_cache_on_delete(sender, instance, **kwargs) -> None:
    cache.delete(make_zone_cache_key(instance.slug))
    logger.debug("Zone cache invalidated on delete: slug=%s", instance.slug)


@receiver(post_save, sender=Advertiser)
def invalidate_advertiser_campaign_caches(sender, instance, **kwargs) -> None:
    zone_ids = (
        AdCampaign.objects
        .filter(advertiser=instance)
        .values_list("zone_id", flat=True)
        .distinct()
    )
    _invalidate_zone_cache_by_ids(zone_ids)
