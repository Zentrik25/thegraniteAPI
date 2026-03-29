import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsPagination
from users.permissions import IsEditorOrAbove

from .models import AuditAction, AuditLog
from .serializers import AuditLogSerializer

logger = logging.getLogger("audit.views")


class AuditLogListView(APIView):
    """
    GET /api/v1/audit/

    Full audit log. Senior Editors and Admins only.

    Query parameters
    ----------------
    ?action=article.published   filter by action type
    ?actor=<username>           filter by actor username
    ?object_id=<id>             filter by object pk
    ?content_type=<model>       filter by model name e.g. article, comment
    ?page=<n>                   page number
    """

    permission_classes = [IsAuthenticated]
    pagination_class   = StandardResultsPagination

    def get(self, request):
        if not (
            request.user.role in ("senior_editor", "admin")
            or request.user.is_superuser
        ):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Only Senior Editors and Admins can access the audit log."
            )

        qs = AuditLog.objects.select_related(
            "actor", "content_type"
        ).order_by("-created_at")

        action       = request.query_params.get("action",       "")
        actor        = request.query_params.get("actor",        "")
        object_id    = request.query_params.get("object_id",    "")
        content_type = request.query_params.get("content_type", "")

        if action:
            qs = qs.filter(action=action)
        if actor:
            qs = qs.filter(actor__username=actor)
        if object_id:
            qs = qs.filter(object_id=object_id)
        if content_type:
            qs = qs.filter(content_type__model=content_type)

        paginator  = self.pagination_class()
        page       = paginator.paginate_queryset(qs, request)
        serializer = AuditLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AuditLogObjectView(APIView):
    """
    GET /api/v1/audit/<content_type>/<object_id>/

    Full audit history for a specific object.
    Useful for seeing the complete history of one article,
    one comment, one user etc.

    Example:
        GET /api/v1/audit/article/42/
        Returns all audit log entries for article pk=42
    """

    permission_classes = [IsAuthenticated, IsEditorOrAbove]

    def get(self, request, content_type_name, object_id):
        from django.contrib.contenttypes.models import ContentType
        from django.shortcuts import get_object_or_404

        content_type = get_object_or_404(
            ContentType, model=content_type_name.lower()
        )

        logs = (
            AuditLog.objects
            .filter(
                content_type=content_type,
                object_id=str(object_id),
            )
            .select_related("actor")
            .order_by("-created_at")
        )

        serializer = AuditLogSerializer(logs, many=True)
        return Response({
            "content_type": content_type_name,
            "object_id":    object_id,
            "count":        logs.count(),
            "results":      serializer.data,
        })