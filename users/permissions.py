from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import EDIT_ANY_ROLES, MANAGE_STAFF_ROLES, PUBLISH_ROLES, StaffRole


class IsStaffUser(BasePermission):
    message = "You must be an active staff member to perform this action."

    def has_permission(self, request, view) -> bool:
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_active
        )

class IsModeratorOrAbove(IsStaffUser):
    message = "You must be a Moderator or above to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.user.role not in (
            StaffRole.CONTRIBUTOR,
            StaffRole.AUTHOR,
        )

class IsContributorOrAbove(IsStaffUser):
    message = "You must be a staff member to perform this action."


class IsAuthorOrAbove(IsStaffUser):
    message = "You must be an Author or above to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.user.role != StaffRole.CONTRIBUTOR


class IsEditorOrAbove(IsStaffUser):
    message = "You must be an Editor or above to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.user.role in PUBLISH_ROLES


class IsSeniorEditorOrAbove(IsStaffUser):
    message = "You must be a Senior Editor or Admin to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.user.role in MANAGE_STAFF_ROLES


class IsAdmin(IsStaffUser):
    message = "You must be an Admin to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.user.role == StaffRole.ADMIN


class CanPublish(IsStaffUser):
    message = "You do not have permission to publish or unpublish articles."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.user.can_publish


class CanEditArticle(IsStaffUser):
    message = "You do not have permission to edit this article."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return request.user.can_edit_article(obj)


class CanManageStaff(IsStaffUser):
    message = "You must be a Senior Editor or Admin to manage staff accounts."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.user.can_manage_staff

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        if obj.role == StaffRole.ADMIN and not request.user.is_editorial_admin:
            return False
        return request.user.can_manage_staff
