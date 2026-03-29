from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):

    list_display  = (
        "created_at",
        "actor",
        "action",
        "object_repr",
        "ip_address",
    )
    list_filter   = ("action",)
    search_fields = (
        "actor__username",
        "object_repr",
        "action",
        "object_id",
    )
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "actor", "action", "content_type", "object_id",
        "object_repr", "metadata", "ip_address", "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False