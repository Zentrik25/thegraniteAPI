import uuid

from django.db import models
from django.utils import timezone


class PushSubscription(models.Model):
    """
    A browser push subscription for one device.

    One reader can have multiple subscriptions — one per device.
    Each subscription has a unique endpoint URL provided by the browser.

    endpoint      The push service URL. Unique per device.
                  Example: https://fcm.googleapis.com/fcm/send/...

    p256dh        Browser public key for message encryption.
    auth          Authentication secret for message encryption.

    user_agent    Browser/device info for debugging.
    is_active     Inactive subscriptions are skipped when sending.
                  Set to False when the endpoint returns 410 Gone.
    """

    id         = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    endpoint   = models.TextField(
        unique=True,
        help_text="Browser push service URL. Unique per device.",
    )
    p256dh     = models.TextField(
        help_text="Browser public key for encryption.",
    )
    auth       = models.TextField(
        help_text="Authentication secret for encryption.",
    )
    user_agent = models.CharField(
        max_length=500,
        blank=True,
        help_text="Browser and device information.",
    )
    is_active  = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Set to False when the endpoint returns 410 Gone.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_used  = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time a notification was sent to this subscription.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(
                fields=["is_active", "created_at"],
                name="notif_active_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"PushSubscription {str(self.id)[:8]}... ({self.user_agent[:50]})"


class Notification(models.Model):
    """
    A record of a push notification that was sent.

    article       The article this notification was about.
    title         Notification title shown in the browser.
    body          Notification body text.
    url           URL the reader is taken to when they click.

    sent_count    How many subscriptions were targeted.
    success_count How many were delivered successfully.
    failed_count  How many failed or were cleaned up.

    sent_at       When the notification was sent.
    """

    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    title         = models.CharField(max_length=255)
    body          = models.TextField(blank=True)
    url           = models.CharField(max_length=500, blank=True)
    icon_url      = models.URLField(blank=True)

    sent_count    = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count  = models.PositiveIntegerField(default=0)

    sent_at    = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self) -> str:
        return f"Notification: {self.title} ({self.sent_at:%Y-%m-%d %H:%M})"