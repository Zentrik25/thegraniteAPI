import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger("notifications.signals")

# Sentinel used to distinguish "attribute not set" from an explicit False.
_UNSET = object()


@receiver(pre_save, sender="articles.Article")
def _capture_breaking_state(sender, instance, **kwargs) -> None:
    """
    Stash the pre-save value of is_breaking on the instance so that
    post_save can compare old vs new without querying the database after
    the save (which would always read the new value).

    New articles (pk is None) get _pre_save_is_breaking = False because
    they have no prior state; the post_save handler treats this as a
    False → True transition when is_breaking is set on creation.
    """
    if instance.pk is None:
        instance._pre_save_is_breaking = False
        return
    try:
        instance._pre_save_is_breaking = (
            sender.objects.only("is_breaking").get(pk=instance.pk).is_breaking
        )
    except sender.DoesNotExist:
        instance._pre_save_is_breaking = False


@receiver(post_save, sender="articles.Article")
def send_breaking_news_notification(sender, instance, created, **kwargs) -> None:
    """
    Send a push notification when an article is first marked as breaking news.

    Only fires when:
    1. The article is published.
    2. is_breaking is True after this save.
    3. is_breaking was False before this save (transition, not no-op re-save).
    """
    if not instance.is_breaking:
        return

    if instance.status != "published":
        return

    # Read the prior state captured in pre_save.  If the attribute is absent
    # (e.g. bulk update path that bypasses signals), fall back to safe default
    # of treating this as a first-time transition so notifications are not
    # silently lost.
    was_breaking = getattr(instance, "_pre_save_is_breaking", _UNSET)
    if was_breaking is _UNSET:
        # bulk-update or other path that skipped pre_save — cannot determine
        # prior state; do not fire to avoid false positives.
        logger.warning(
            "send_breaking_news_notification: _pre_save_is_breaking not set "
            "for article pk=%s; skipping notification.",
            instance.pk,
        )
        return

    if was_breaking:
        # Already was breaking before this save — do not send duplicate.
        return

    try:
        # Web push makes external HTTP calls.  Defer until after the DB
        # transaction commits so a rolled-back save never fires a push, and
        # the request thread is not held waiting on external latency.
        # In TestCase tests the transaction never commits, so this is a
        # no-op there — which prevents real push calls during test runs.
        pk   = instance.pk
        slug = instance.slug

        def _push():
            from .tasks import send_breaking_news_push
            send_breaking_news_push.apply_async(args=[pk], queue="slow")
            logger.info(
                "Breaking news notification queued: article pk=%s slug=%s",
                pk,
                slug,
            )

        transaction.on_commit(_push)

    except Exception as exc:
        logger.error(
            "Failed to queue breaking news notification for article pk=%s: %s",
            instance.pk,
            exc,
        )