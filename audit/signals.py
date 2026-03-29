import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("audit.signals")


@receiver(post_save, sender="articles.Article")
def log_article_status_change(sender, instance, created, **kwargs) -> None:
    """Log article creation, publish, and archive events."""
    try:
        from .models import AuditAction
        from .utils import log_action

        if created:
            action = AuditAction.ARTICLE_CREATED
        elif instance.status == "published":
            action = AuditAction.ARTICLE_PUBLISHED
        elif instance.status == "archived":
            action = AuditAction.ARTICLE_ARCHIVED
        else:
            action = AuditAction.ARTICLE_UPDATED

        log_action(
            action      = action,
            obj         = instance,
            object_repr = str(instance),
            metadata    = {
                "slug":   instance.slug,
                "status": instance.status,
                "title":  instance.title,
            },
        )
    except Exception as exc:
        logger.error("Failed to log article action: %s", exc)


@receiver(post_save, sender="comments.Comment")
def log_comment_action(sender, instance, created, **kwargs) -> None:
    """Log comment submission and moderation actions."""
    try:
        from .models import AuditAction
        from .utils import log_action

        if created:
            action = AuditAction.COMMENT_SUBMITTED
        elif instance.status == "approved":
            action = AuditAction.COMMENT_APPROVED
        elif instance.status == "rejected":
            action = AuditAction.COMMENT_REJECTED
        else:
            return

        log_action(
            action      = action,
            obj         = instance,
            object_repr = str(instance),
            metadata    = {
                "article_slug": instance.article.slug,
                "author_name":  instance.author_name,
                "status":       instance.status,
            },
        )
    except Exception as exc:
        logger.error("Failed to log comment action: %s", exc)


@receiver(post_save, sender="users.StaffUser")
def log_user_action(sender, instance, created, **kwargs) -> None:
    """Log user creation and role changes."""
    try:
        from .models import AuditAction
        from .utils import log_action

        if created:
            log_action(
                action      = AuditAction.USER_CREATED,
                obj         = instance,
                object_repr = str(instance),
                metadata    = {
                    "username": instance.username,
                    "role":     instance.role,
                },
            )
    except Exception as exc:
        logger.error("Failed to log user action: %s", exc)


@receiver(post_save, sender="redirects.Redirect")
def log_redirect_action(sender, instance, created, **kwargs) -> None:
    """Log redirect creation and updates."""
    try:
        from .models import AuditAction
        from .utils import log_action

        action = AuditAction.REDIRECT_CREATED if created else AuditAction.REDIRECT_UPDATED

        log_action(
            action      = action,
            obj         = instance,
            object_repr = str(instance),
            metadata    = {
                "old_path":   instance.old_path,
                "new_path":   instance.new_path,
                "created_by": instance.created_by,
            },
        )
    except Exception as exc:
        logger.error("Failed to log redirect action: %s", exc)