import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("search.signals")


@receiver(post_save, sender="articles.Article")
def update_search_vector(sender, instance, **kwargs) -> None:
    """
    Rebuild the search vector for an article every time it is saved.

    We use update_fields to avoid triggering this signal again
    (which would cause infinite recursion).

    The vector is only rebuilt for published articles — there is no
    value in indexing drafts or archived articles for reader search.
    """
    from django.contrib.postgres.search import SearchVector

    if instance.status != "published":
        return

    try:
        with transaction.atomic():
            sender.objects.filter(pk=instance.pk).update(
                search_vector=(
                    SearchVector("title",   weight="A", config="english") +
                    SearchVector("excerpt", weight="B", config="english") +
                    SearchVector("body",    weight="C", config="english")
                )
            )
        logger.debug(
            "Search vector updated: article pk=%s slug=%s",
            instance.pk,
            instance.slug,
        )
    except Exception as exc:
        logger.error(
            "Failed to update search vector for article pk=%s: %s",
            instance.pk,
            exc,
        )
