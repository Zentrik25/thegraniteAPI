import hashlib

from django.db import models
from django.utils import timezone


class ArticleView(models.Model):
    """
    Records one view per IP address per article per calendar day.

    ip_hash      — SHA-256 of the raw IP. Never store raw IPs.
    session_hash — SHA-256 of the Django session key for additional
                   deduplication when the same IP is shared (e.g. office NAT).
    viewed_date  — the calendar date, used in the UniqueConstraint.
                   Stored separately from viewed_at so the constraint
                   does not need a date truncation function.
    """

    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.CASCADE,
        related_name="views",
    )
    ip_hash      = models.CharField(max_length=64)
    session_hash = models.CharField(max_length=64, blank=True)
    viewed_at    = models.DateTimeField(default=timezone.now, db_index=True)
    viewed_date  = models.DateField(db_index=True)

    class Meta:
        constraints = [
            # One view per IP per article per day — enforced at DB level.
            models.UniqueConstraint(
                fields=["article", "ip_hash", "viewed_date"],
                name="analytics_one_view_per_ip_per_day",
            ),
        ]
        indexes = [
            models.Index(
                fields=["article", "viewed_at"],
                name="analytics_article_time_idx",
            ),
            models.Index(
                fields=["viewed_date"],
                name="analytics_date_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"View article_id={self.article_id} on {self.viewed_date}"

    @staticmethod
    def hash_ip(ip: str) -> str:
        """SHA-256 hash of an IP address. One-way — cannot be reversed."""
        return hashlib.sha256(ip.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_session(session_key: str) -> str:
        """SHA-256 hash of a session key. Returns empty string if no session."""
        if not session_key:
            return ""
        return hashlib.sha256(session_key.encode("utf-8")).hexdigest()
