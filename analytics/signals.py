import logging

from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("analytics.signals")


@receiver(post_save, sender="analytics.ArticleView")
def increment_article_view_count(sender, instance, created, **kwargs) -> None:
    """
    Increment Article.view_count by 1 each time a new ArticleView is created.

    Uses F() expression — a single atomic SQL UPDATE:
        UPDATE articles SET view_count = view_count + 1 WHERE id = <id>

    This is safe under concurrent requests. Two simultaneous views on the
    same article will each increment by 1 without overwriting each other,
    which is what a plain Python increment would do:
        article.view_count += 1  ← WRONG: race condition
        article.save()           ← WRONG: second save overwrites first
    """
    if not created:
        return

    from articles.models import Article

    Article.objects.filter(pk=instance.article_id).update(
        view_count=F("view_count") + 1
    )
    logger.debug(
        "View count incremented: article_id=%s date=%s",
        instance.article_id,
        instance.viewed_date,
    )
