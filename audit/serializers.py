from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only audit log entry."""

    actor_username   = serializers.SerializerMethodField()
    action_display   = serializers.SerializerMethodField()
    content_type_name = serializers.SerializerMethodField()

    class Meta:
        model  = AuditLog
        fields = (
            "id",
            "actor_username",
            "action",
            "action_display",
            "content_type_name",
            "object_id",
            "object_repr",
            "metadata",
            "ip_address",
            "created_at",
        )

    def get_actor_username(self, obj) -> str:
        if obj.actor:
            return obj.actor.username
        return "system"

    def get_action_display(self, obj) -> str:
        return obj.get_action_display()

    def get_content_type_name(self, obj) -> str:
        if obj.content_type:
            return obj.content_type.model
        return ""