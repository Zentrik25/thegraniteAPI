import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsPagination
from users.permissions import IsEditorOrAbove

from .models import Redirect
from .serializers import RedirectSerializer, RedirectWriteSerializer

logger = logging.getLogger("redirects.views")


class RedirectListView(APIView):
    """
    GET  /api/v1/redirects/   — list all redirects (Editor and above)
    POST /api/v1/redirects/   — create a redirect (Editor and above)

    ?active=true    active redirects only (default)
    ?active=false   inactive redirects only
    ?active=all     all redirects
    ?search=<path>  filter by old_path containing this string
    """

    permission_classes = [IsAuthenticated, IsEditorOrAbove]
    pagination_class   = StandardResultsPagination

    def get(self, request):
        active_param = request.query_params.get("active", "true")
        search       = request.query_params.get("search", "").strip()

        qs = Redirect.objects.all()

        if active_param == "true":
            qs = qs.filter(is_active=True)
        elif active_param == "false":
            qs = qs.filter(is_active=False)

        if search:
            qs = qs.filter(old_path__icontains=search)

        qs = qs.order_by("-created_at")

        paginator  = self.pagination_class()
        page       = paginator.paginate_queryset(qs, request)
        serializer = RedirectSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = RedirectWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        redirect = serializer.save(created_by="manual")
        logger.info(
            "Redirect created manually: %s → %s by user=%s",
            redirect.old_path,
            redirect.new_path,
            request.user.pk,
        )
        return Response(
            RedirectSerializer(redirect).data,
            status=status.HTTP_201_CREATED,
        )


class RedirectDetailView(APIView):
    """
    GET    /api/v1/redirects/<id>/   — retrieve a redirect
    PATCH  /api/v1/redirects/<id>/   — update a redirect
    DELETE /api/v1/redirects/<id>/   — delete a redirect
    """

    permission_classes = [IsAuthenticated, IsEditorOrAbove]

    def get(self, request, pk):
        redirect = get_object_or_404(Redirect, pk=pk)
        return Response(RedirectSerializer(redirect).data)

    def patch(self, request, pk):
        redirect   = get_object_or_404(Redirect, pk=pk)
        serializer = RedirectWriteSerializer(
            redirect, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        redirect = serializer.save()
        _clear_cache(redirect.old_path)
        logger.info(
            "Redirect updated: pk=%s %s → %s by user=%s",
            redirect.pk,
            redirect.old_path,
            redirect.new_path,
            request.user.pk,
        )
        return Response(RedirectSerializer(redirect).data)

    def delete(self, request, pk):
        redirect = get_object_or_404(Redirect, pk=pk)
        old_path = redirect.old_path
        redirect.delete()
        _clear_cache(old_path)
        logger.info(
            "Redirect deleted: pk=%s path=%s by user=%s",
            pk,
            old_path,
            request.user.pk,
        )
        return Response(
            {"detail": f"Redirect for '{old_path}' has been deleted."},
            status=status.HTTP_200_OK,
        )


def _clear_cache(old_path: str) -> None:
    try:
        from django.core.cache import cache
        from core.cache import make_cache_key
        cache.delete(make_cache_key(f"redirect:{old_path}"))
    except Exception:
        pass