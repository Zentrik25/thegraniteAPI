from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from django.utils.html import format_html

from .models import StaffRole, StaffUser

_ROLE_COLOURS = {
    StaffRole.CONTRIBUTOR:   "#6b7280",
    StaffRole.AUTHOR:        "#2563eb",
    StaffRole.EDITOR:        "#7c3aed",
    StaffRole.SENIOR_EDITOR: "#b45309",
    StaffRole.ADMIN:         "#dc2626",
}


@admin.register(StaffUser)
class StaffUserAdmin(UserAdmin):

    list_display  = (
        "byline",
        "username",
        "email",
        "role_badge",
        "title",
        "is_active",
        "date_joined",
    )
    list_filter   = ("role", "is_active", "is_staff")
    search_fields = (
        "username", "email", "first_name",
        "last_name", "display_name", "beat",
    )
    ordering      = ("role", "last_name")

    fieldsets = (
        (None, {
            "fields": ("username", "password"),
        }),
        ("Name & Role", {
            "fields": (
                "first_name", "last_name", "display_name",
                "slug", "role", "title", "is_active",
            ),
        }),
        ("Public Profile", {
            "fields": ("bio", "avatar_url", "beat"),
            "classes": ("collapse",),
        }),
        ("Contact & Social", {
            "fields": ("email", "email_public", "twitter_handle", "linkedin_url"),
            "classes": ("collapse",),
        }),
        ("Django Permissions", {
            "fields": ("is_staff", "is_superuser", "groups", "user_permissions"),
            "classes": ("collapse",),
        }),
        ("Dates", {
            "fields": ("last_login", "date_joined"),
            "classes": ("collapse",),
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "username", "email", "first_name",
                "last_name", "role", "password1", "password2",
            ),
        }),
    )

    readonly_fields = ("slug", "date_joined", "last_login")

    actions = ["action_deactivate", "action_activate"]

    @admin.action(description="🚫  Deactivate selected accounts")
    def action_deactivate(self, request, queryset):
        updated = queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, f"{updated} account(s) deactivated.")

    @admin.action(description="✅  Activate selected accounts")
    def action_activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} account(s) activated.")

    @admin.display(description="Role", ordering="role")
    def role_badge(self, obj):
        colour = _ROLE_COLOURS.get(obj.role, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
            colour,
            obj.get_role_display().upper(),
        )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_editorial_admin:
            readonly.append("role")
        if obj and obj.role == StaffRole.ADMIN and not request.user.is_editorial_admin:
            readonly += ["is_active", "is_staff", "is_superuser"]
        return readonly

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        if obj is None:
            return request.user.can_manage_staff
        if obj == request.user:
            return True
        return request.user.can_manage_staff

    def has_add_permission(self, request) -> bool:
        return request.user.can_manage_staff
