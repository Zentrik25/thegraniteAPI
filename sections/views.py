import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.serializers import ArticleListSerializer
from core.cache import get_or_set_cache
from core.pagination import StandardResultsPagination
from users.permissions import IsEditorOrAbove

from .models import Section
from .serializers import (
    SectionDetailSerializer,
    SectionSerializer,
    SectionWriteSerializer,
)

logger = logging.getLogger("sections.views")

SECTION_LIST_TTL   = 300
SECTION_DETAIL_TTL = 120


class SectionListView(APIView):
    """
    GET  /api/v1/sections/   — list all active sections (public)
    POST /api/v1/sections/   — create a section (Editor and above)

    ?primary=true   — primary sections only (main nav)
    ?primary=false  — secondary sections only (dropdown/footer)
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsEditorOrAbove()]
        return [AllowAny()]

    def get(self, request):
        primary_param = request.query_params.get("primary", None)
        cache_key     = "sections:list"

        if primary_param == "true":
            cache_key = "sections:list:primary"
        elif primary_param == "false":
            cache_key = "sections:list:secondary"

        def compute():
            qs = Section.objects.filter(is_active=True)
            if primary_param == "true":
                qs = qs.filter(is_primary=True)
            elif primary_param == "false":
                qs = qs.filter(is_primary=False)
            serializer = SectionSerializer(
                qs, many=True, context={"request": request}
            )
            return serializer.data

        data = get_or_set_cache(cache_key, compute, ttl=SECTION_LIST_TTL)
        return Response({
            "status":  "ok",
            "count":   len(data),
            "results": data,
        })

    def post(self, request):
        serializer = SectionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        section = serializer.save()
        logger.info(
            "Section created: pk=%s name=%s by user=%s",
            section.pk,
            section.name,
            request.user.pk,
        )
        return Response(
            SectionSerializer(section, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class SectionDetailView(APIView):
    """
    GET    /api/v1/sections/<slug>/   — detail + hero + categories + 20 articles
    PATCH  /api/v1/sections/<slug>/   — update (Editor and above)
    DELETE /api/v1/sections/<slug>/   — deactivate (Editor and above)
    """

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated(), IsEditorOrAbove()]
        return [AllowAny()]

    def get_section(self, slug, active_only=True):
        qs = Section.objects.select_related("featured_article")
        if active_only:
            qs = qs.filter(is_active=True)
        return get_object_or_404(qs, slug=slug)

    def get(self, request, slug):
        def compute():
            section    = self.get_section(slug)
            serializer = SectionDetailSerializer(
                section, context={"request": request}
            )
            return serializer.data

        data = get_or_set_cache(
            f"sections:detail:{slug}",
            compute,
            ttl=SECTION_DETAIL_TTL,
        )
        return Response(data)

    def patch(self, request, slug):
        section    = self.get_section(slug, active_only=False)
        serializer = SectionWriteSerializer(
            section, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        section = serializer.save()
        logger.info(
            "Section updated: pk=%s slug=%s by user=%s",
            section.pk,
            section.slug,
            request.user.pk,
        )
        return Response(
            SectionSerializer(section, context={"request": request}).data
        )

    def delete(self, request, slug):
        section           = self.get_section(slug, active_only=False)
        name              = section.name
        section.is_active = False
        section.save(update_fields=["is_active", "updated_at"])
        logger.info(
            "Section deactivated: pk=%s slug=%s by user=%s",
            section.pk,
            section.slug,
            request.user.pk,
        )
        return Response(
            {"detail": f"Section '{name}' has been deactivated."},
            status=status.HTTP_200_OK,
        )


class SectionArticlesView(APIView):
    """
    GET /api/v1/sections/<slug>/articles/

    Paginated feed of all published articles in a section.
    ?category=<slug>  filter by category within the section
    """

    permission_classes = [AllowAny]
    pagination_class   = StandardResultsPagination

    def get(self, request, slug):
        from articles.models import Article, PublishStatus

        section = get_object_or_404(Section, slug=slug, is_active=True)

        articles = (
            Article.objects
            .filter(
                category__section=section,
                status=PublishStatus.PUBLISHED,
            )
            .with_related()
            .order_by("-published_at")
        )

        category_slug = request.query_params.get("category", None)
        if category_slug:
            articles = articles.filter(category__slug=category_slug)

        paginator  = self.pagination_class()
        page       = paginator.paginate_queryset(articles, request)
        serializer = ArticleListSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)