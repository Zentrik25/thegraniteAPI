from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class AuditAction(models.TextChoices):
    # Article actions
    ARTICLE_CREATED    = "article.created",    "Article Created"
    ARTICLE_UPDATED    = "article.updated",    "Article Updated"
    ARTICLE_PUBLISHED  = "article.published",  "Article Published"
    ARTICLE_ARCHIVED   = "article.archived",   "Article Archived"
    ARTICLE_DELETED    = "article.deleted",    "Article Deleted"

    # Comment actions
    COMMENT_SUBMITTED  = "comment.submitted",  "Comment Submitted"
    COMMENT_APPROVED   = "comment.approved",   "Comment Approved"
    COMMENT_REJECTED   = "comment.rejected",   "Comment Rejected"
    COMMENT_DELETED    = "comment.deleted",    "Comment Deleted"

    # User actions
    USER_CREATED       = "user.created",       "User Created"
    USER_ROLE_CHANGED  = "user.role_changed",  "User Role Changed"
    USER_DEACTIVATED   = "user.deactivated",   "User Deactivated"
    USER_LOGIN         = "user.login",         "User Login"
    USER_PASSWORD_CHANGED = "user.password_changed", "Password Changed"

    # Redirect actions
    REDIRECT_CREATED   = "redirect.created",   "Redirect Created"
    REDIRECT_UPDATED   = "redirect.updated",   "Redirect Updated"
    REDIRECT_DELETED   = "redirect.deleted",   "Redirect Deleted"

    # Section actions
    SECTION_CREATED    = "section.created",    "Section Created"
    SECTION_UPDATED    = "section.updated",    "Section Updated"
    SECTION_DEACTIVATED = "section.deactivated", "Section Deactivated"

    # Media actions
    MEDIA_UPLOADED     = "media.uploaded",     "Media Uploaded"
    MEDIA_DELETED      = "media.deleted",      "Media Deleted"

    # Newsletter actions
    NEWSLETTER_SUBSCRIBED   = "newsletter.subscribed",   "Newsletter Subscribed"
    NEWSLETTER_UNSUBSCRIBED = "newsletter.unsubscribed", "Newsletter Unsubscribed"


class AuditLog(models.Model):
    """
    Immutable record of every editorial action in the newsroom.

    Uses Django's ContentType framework so one model covers
    every object type — articles, comments, users, redirects etc.

    actor         The staff member who performed the action.
                  Null if the action was performed by a Celery task
                  or management command.

    action        What happened. One of the AuditAction choices.

    content_type  The type of object the action was performed on.
    object_id     The pk of that object.
    content_object The actual object (resolved via GenericFK).

    object_repr   A string snapshot of the object at the time of the action.
                  Stored so the log is still meaningful even if the object
                  is later deleted.

    metadata      JSON field for any extra context (e.g. old role → new role,
                  old slug → new slug).

    ip_address    IP address of the actor for security auditing.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text="Staff member who performed the action. "
                  "Null for system/automated actions.",
    )
    action = models.CharField(
        max_length=50,
        choices=AuditAction.choices,
        db_index=True,
        help_text="What action was performed.",
    )

    # Generic FK — points to any model.
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    object_id     = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
    )
    content_object = GenericForeignKey("content_type", "object_id")

    object_repr = models.CharField(
        max_length=500,
        blank=True,
        help_text="String snapshot of the object at the time of the action.",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra context e.g. old role, new role, old slug, new slug.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the actor.",
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(
                fields=["action", "created_at"],
                name="audit_action_created_idx",
            ),
            models.Index(
                fields=["actor", "created_at"],
                name="audit_actor_created_idx",
            ),
            models.Index(
                fields=["content_type", "object_id"],
                name="audit_content_object_idx",
            ),
        ]

    def __str__(self) -> str:
        actor = self.actor.username if self.actor else "system"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor} — {self.action}"