from rest_framework import serializers

from .models import Subscriber


class SubscribeSerializer(serializers.Serializer):
    """Input for POST /api/v1/newsletter/subscribe/"""

    email  = serializers.EmailField()
    source = serializers.CharField(
        max_length=100,
        required=False,
        default="",
        help_text="Where the subscription originated e.g. footer, article-cta.",
    )

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class UnsubscribeSerializer(serializers.Serializer):
    """Input for POST /api/v1/newsletter/unsubscribe/"""

    token = serializers.UUIDField(
        help_text="The unsubscribe token from the email footer."
    )


class SubscriberSerializer(serializers.ModelSerializer):
    """
    Full subscriber record for the admin list endpoint.
    Only visible to Senior Editors and above.
    confirmation_token is excluded — no need to expose it via API.
    """

    class Meta:
        model  = Subscriber
        fields = (
            "id",
            "email",
            "confirmed",
            "source",
            "confirmed_at",
            "created_at",
        )
        read_only_fields = fields
