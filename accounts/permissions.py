"""
permissions.py — DRF permission classes for reader account endpoints.
"""

from rest_framework.permissions import BasePermission


class IsReader(BasePermission):
    """
    Allow access only to authenticated ReaderAccount instances.

    Prevents staff JWT tokens (which resolve to StaffUser) from being
    used on reader-only endpoints, and vice versa.
    """

    message = "This endpoint is for registered readers only."

    def has_permission(self, request, view) -> bool:
        from .models import ReaderAccount

        return (
            request.user is not None
            and isinstance(request.user, ReaderAccount)
            and request.user.is_active
        )
