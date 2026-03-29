from rest_framework import serializers

from .models import Redirect


class RedirectSerializer(serializers.ModelSerializer):
    """Full redirect record for the admin API."""

    class Meta:
        model  = Redirect
        fields = (
            "id",
            "old_path",
            "new_path",
            "is_active",
            "hits",
            "created_by",
            "note",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "hits", "created_at", "updated_at")


class RedirectWriteSerializer(serializers.ModelSerializer):
    """Input for creating and updating redirects."""

    class Meta:
        model  = Redirect
        fields = (
            "old_path",
            "new_path",
            "is_active",
            "note",
        )

    def validate_old_path(self, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            value = f"/{value}"
        return value

    def validate_new_path(self, value: str) -> str:
        value = value.strip()
        if not value.startswith("/") and not value.startswith("http"):
            value = f"/{value}"
        return value

    def validate(self, data):
        old_path = data.get("old_path", "")
        new_path = data.get("new_path", "")
        if old_path and new_path and old_path == new_path:
            raise serializers.ValidationError(
                "Old path and new path cannot be the same. "
                "This would create an infinite redirect loop."
            )
        return data