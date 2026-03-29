"""
models.py — Reader account models for The Granite Post.

Reader accounts are completely separate from editorial StaffUser accounts.
The same email may appear in both — they are distinct entities with different
authentication flows.

Model inventory:
  ReaderAccount        — registered reader with UUID PK and hashed password
  Bookmark             — saved article; one per reader per article
  ReadingHistory       — reading events; one record per reader/article with
                         a running read_count incremented atomically with F()
  BlacklistedReaderToken — revoked reader JWT refresh tokens (jti store)
"""

import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Reader account
# ---------------------------------------------------------------------------

class ReaderAccount(models.Model):
    """
    A registered reader.

    is_email_verified must be True before login is permitted.
    email_verification_token is regenerated after each successful verification
    so it cannot be replayed.

    password_reset_token is set on a forgot-password request and expires after
    1 hour (enforced by the view). It is cleared to None after use.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    email = models.EmailField(
        unique=True,
        db_index=True,
        help_text="Login identifier. Stored lower-cased.",
    )
    username = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Public handle shown on comments and profile pages.",
    )
    display_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Friendly name. Falls back to username when blank.",
    )
    avatar_url = models.URLField(
        blank=True,
        help_text="Externally hosted profile picture URL.",
    )
    bio = models.TextField(
        blank=True,
        max_length=500,
        help_text="Short reader biography. Max 500 characters.",
    )

    # ------------------------------------------------------------------
    # Auth fields
    # ------------------------------------------------------------------

    password = models.CharField(
        max_length=255,
        help_text="Hashed password. Set via set_password(), never directly.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Inactive readers cannot log in.",
    )
    is_email_verified = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Must be True before the reader can log in.",
    )
    email_verification_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        help_text="Token sent in the verification email. Expires 24 h after registration.",
    )

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------

    password_reset_token = models.UUIDField(
        null=True,
        blank=True,
        help_text="One-time token for password reset. Expires after 1 hour.",
    )
    password_reset_token_expires = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expiry timestamp for the password reset token.",
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------

    date_joined = models.DateTimeField(auto_now_add=True, db_index=True)
    last_login  = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Stamped on each successful login.",
    )

    class Meta:
        ordering            = ["-date_joined"]
        verbose_name        = "Reader Account"
        verbose_name_plural = "Reader Accounts"
        indexes = [
            models.Index(
                fields=["is_active", "is_email_verified"],
                name="reader_active_verified_idx",
            ),
            models.Index(
                fields=["email", "is_active"],
                name="reader_email_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.username} <{self.email}>"

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def set_password(self, raw_password: str) -> None:
        """Hash *raw_password* and store it. Does not call save()."""
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Return True if *raw_password* matches the stored hash."""
        return check_password(raw_password, self.password)

    # ------------------------------------------------------------------
    # DRF duck-typing — satisfies IsAuthenticated and permission checks
    # ------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        """Always True for a resolved ReaderAccount."""
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def is_staff(self) -> bool:
        return False

    @property
    def is_superuser(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @property
    def public_name(self) -> str:
        """Best available public display name."""
        return self.display_name or self.username


# ---------------------------------------------------------------------------
# Bookmark
# ---------------------------------------------------------------------------

class Bookmark(models.Model):
    """
    A saved article for a reader.

    UniqueConstraint on (reader, article) — one bookmark per article per
    reader, enforced at the DB level. Duplicate attempts raise IntegrityError;
    the view handles this explicitly.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    reader = models.ForeignKey(
        ReaderAccount,
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )
    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["reader", "article"],
                name="bookmark_unique_reader_article",
            ),
        ]
        indexes = [
            models.Index(
                fields=["reader", "created_at"],
                name="bookmark_reader_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Bookmark: {self.reader.username} → article {self.article_id}"


# ---------------------------------------------------------------------------
# Reading history
# ---------------------------------------------------------------------------

class ReadingHistory(models.Model):
    """
    One record per reader per article.

    read_count is incremented atomically with F() on each re-visit.
    read_at is updated to the time of the most recent visit.

    UniqueConstraint on (reader, article) ensures a single record exists
    per reader/article pair.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    reader = models.ForeignKey(
        ReaderAccount,
        on_delete=models.CASCADE,
        related_name="reading_history",
    )
    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.CASCADE,
        related_name="reading_history",
    )
    read_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="Timestamp of the most recent read.",
    )
    read_count = models.PositiveIntegerField(
        default=1,
        help_text="How many times this reader has read this article.",
    )

    class Meta:
        ordering = ["-read_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["reader", "article"],
                name="history_unique_reader_article",
            ),
        ]
        indexes = [
            models.Index(
                fields=["reader", "read_at"],
                name="history_reader_read_at_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"History: {self.reader.username} "
            f"read article {self.article_id} × {self.read_count}"
        )


# ---------------------------------------------------------------------------
# Token blacklist
# ---------------------------------------------------------------------------

class BlacklistedReaderToken(models.Model):
    """
    Stores the JTI (JWT ID) of revoked reader refresh tokens.

    On logout, the token's jti is inserted here. The token refresh view
    rejects any token whose jti is present in this table.
    """

    jti = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="JWT ID (jti claim) of the blacklisted refresh token.",
    )
    blacklisted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering            = ["-blacklisted_at"]
        verbose_name        = "Blacklisted Reader Token"
        verbose_name_plural = "Blacklisted Reader Tokens"

    def __str__(self) -> str:
        return f"Blacklisted JTI: {self.jti[:24]}…"
