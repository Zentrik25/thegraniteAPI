from rest_framework import serializers

from .models import Notification, PushSubscription


class PushSubscriptionSerializer(serializers.ModelSerializer):
    """Response after subscribing."""

    class Meta:
        model  = PushSubscription
        fields = ("id", "created_at")
        read_only_fields = fields


class PushSubscribeSerializer(serializers.Serializer):
    """
    Input for POST /api/v1/notifications/subscribe/

    The browser provides these values from the PushSubscription object
    it receives after calling pushManager.subscribe().
    """

    endpoint   = serializers.CharField(
        help_text="Push service URL from the browser PushSubscription.",
    )
    p256dh     = serializers.CharField(
        help_text="Browser public key from PushSubscription.getKey('p256dh').",
    )
    auth       = serializers.CharField(
        help_text="Auth secret from PushSubscription.getKey('auth').",
    )
    user_agent = serializers.CharField(
        required=False,
        default="",
        max_length=500,
        help_text="Browser user agent string.",
    )

    def validate_endpoint(self, value: str) -> str:
        if not value.startswith("https://"):
            raise serializers.ValidationError(
                "Push endpoint must be an HTTPS URL."
            )
        return value


class NotificationSerializer(serializers.ModelSerializer):
    """Notification record for the admin log."""

    article_slug = serializers.SerializerMethodField()

    class Meta:
        model  = Notification
        fields = (
            "id",
            "title",
            "body",
            "url",
            "article_slug",
            "sent_count",
            "success_count",
            "failed_count",
            "sent_at",
        )

    def get_article_slug(self, obj) -> str:
        if obj.article:
            return obj.article.slug
        return ""