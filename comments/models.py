import hashlib

from django.db import models
from django.utils import timezone


class CommentStatus(models.TextChoices):
    PENDING  = "pending",  "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Comment(models.Model):
    """
    A reader comment on a published article.

    Moderation flow: PENDING → APPROVED (visible) or REJECTED (hidden).
    Threading: one level only. parent is null for top-level comments.
    A reply points to a top-level comment. Replies to replies are rejected
    at the serializer layer.

    author_email is stored for moderation purposes only.
    It is never returned in the public serializer.

    ip_hash is SHA-256 of the commenter's IP address.
    Raw IPs are never stored.
    """

    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )

    author_name  = models.CharField(max_length=100)
    author_email = models.EmailField()
    body         = models.TextField(max_length=2000)

    status = models.CharField(
        max_length=10,
        choices=CommentStatus.choices,
        default=CommentStatus.PENDING,
        db_index=True,
    )

    ip_hash    = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes  = [
            models.Index(
                fields=["article", "status", "created_at"],
                name="comments_article_status_idx",
            ),
            models.Index(
                fields=["status", "created_at"],
                name="comments_status_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Comment by {self.author_name} on article {self.article_id}"

    @staticmethod
    def hash_ip(ip: str) -> str:
        return hashlib.sha256(ip.encode("utf-8")).hexdigest()

    @property
    def is_reply(self) -> bool:
        return self.parent_id is not None

    @property
    def is_approved(self) -> bool:
        return self.status == CommentStatus.APPROVED
