import logging

from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger("audit.utils")


def log_action(
    action: str,
    actor=None,
    obj=None,
    object_repr: str = "",
    metadata: dict = None,
    ip_address: str = None,
) -> None:
    """
    Create an AuditLog entry.

    Call this from any view or signal to record an action.

    Parameters
    ----------
    action       One of the AuditAction choices e.g. "article.published"
    actor        The StaffUser who performed the action. None for system actions.
    obj          The object the action was performed on. Any model instance.
    object_repr  String description of the object. Auto-generated if not provided.
    metadata     Dict of extra context e.g. {"old_role": "author", "new_role": "editor"}
    ip_address   IP address of the actor.

    Example
    -------
    from audit.utils import log_action
    from audit.models import AuditAction

    log_action(
        action      = AuditAction.ARTICLE_PUBLISHED,
        actor       = request.user,
        obj         = article,
        metadata    = {"slug": article.slug},
        ip_address  = request.META.get("REMOTE_ADDR"),
    )
    """
    try:
        from .models import AuditLog

        content_type = None
        object_id    = ""

        if obj is not None:
            content_type = ContentType.objects.get_for_model(obj)
            object_id    = str(obj.pk)
            if not object_repr:
                object_repr = str(obj)[:500]

        AuditLog.objects.create(
            actor        = actor,
            action       = action,
            content_type = content_type,
            object_id    = object_id,
            object_repr  = object_repr,
            metadata     = metadata or {},
            ip_address   = ip_address,
        )
    except Exception as exc:
        # Never let audit logging break the main flow.
        logger.error("Failed to create audit log: %s", exc)