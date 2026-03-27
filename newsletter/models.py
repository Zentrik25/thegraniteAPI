import uuid

from django.db import models
from django.utils import timezone


class Subscriber(models.Model):
    """
    A newsletter subscriber.

    Double opt-in flow:
      1. Reader submits email → confirmed=False, confirmation email sent
      2. Reader clicks confirmation link → confirmed=True

    unsubscribe_token is a UUID that never expires.
    It is included in every newsletter footer so readers can
    opt out at any time without needing to log in.

    source tracks where the subscription originated so the
    editorial team knows which placement drives the most signups.
    """

    email = models.EmailField(
        unique=True,
        help_text="Subscriber email address.",
    )
    confirmed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True once the subscriber has clicked the confirmation link.",
    )
    confirmation_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Token sent in the confirmation email. One-time use.",
    )
    unsubscribe_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Token included in every email footer. Never expires.",
    )
    source = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Where the subscription originated e.g. footer, article-cta, homepage.",
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the subscriber confirmed their email.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(
                fields=["confirmed", "created_at"],
                name="nl_confirmed_created_idx",
            ),
        ]

    def __str__(self) -> str:
        status = "confirmed" if self.confirmed else "unconfirmed"
        return f"{self.email} ({status})"

    def confirm(self) -> None:
        """Mark this subscriber as confirmed."""
        if not self.confirmed:
            self.confirmed    = True
            self.confirmed_at = timezone.now()
            self.save(update_fields=["confirmed", "confirmed_at"])

    def unsubscribe(self) -> None:
        """Remove this subscriber by deleting their record."""
        self.delete()
