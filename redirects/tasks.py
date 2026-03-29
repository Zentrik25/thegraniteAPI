import logging

from celery import shared_task
from django.db.models import F

logger = logging.getLogger("redirects.tasks")


@shared_task(
    queue="slow",
    ignore_result=True,
    name="redirects.tasks.increment_redirect_hits",
)
def increment_redirect_hits(old_path: str) -> None:
    """
    Increment the hit counter for a redirect atomically.
    Called by the middleware via Celery so it does not
    slow down the redirect response.
    """
    try:
        from .models import Redirect
        updated = Redirect.objects.filter(
            old_path=old_path,
            is_active=True,
        ).update(hits=F("hits") + 1)

        if updated:
            logger.debug("Hit recorded: %s", old_path)
    except Exception as exc:
        logger.error(
            "Failed to increment hits for path %s: %s",
            old_path,
            exc,
        )