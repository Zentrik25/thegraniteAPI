import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import Article
from core.middleware import _get_client_ip
from core.pagination import StandardResultsPagination
from users.permissions import IsEditorOrAbove, IsModeratorOrAbove

from .models import Comment, CommentStatus
from .serializers import (
    CommentModerationSerializer,
    CommentPublicSerializer,
    CommentWriteSerializer,
    ModerationActionSerializer,
)
from .throttling import CommentRateThrottle

logger = logging.getLogger("comments.views")


class ArticleCommentsView(APIView):
    """
    GET  /api/v1/articles/<slug>/comments/
    POST /api/v1/articles/<slug>/comments/

    GET  — returns all approved top-level comments with their approved replies.
    POST — submits a new comment. Goes into PENDING moderation queue.
           Rate limited to 3 per IP per hour.
    """

    def get_permissions(self):
        return [AllowAny()]

    def get_throttles(self):
        if self.request.method == "POST":
            return [CommentRateThrottle()]
        return []

    def get_article(self, slug):
        return get_object_or_404(Article.objects.published(), slug=slug)

    def get(self, request, slug):
        article = self.get_article(slug)

        comments = (
            Comment.objects
            .filter(
                article=article,
                status=CommentStatus.APPROVED,
                parent__isnull=True,
            )
            .select_related("article")
            .prefetch_related("replies")
            .order_by("created_at")
        )

        serializer = CommentPublicSerializer(comments, many=True)
        return Response({
            "count":    comments.count(),
            "results":  serializer.data,
        })

    def post(self, request, slug):
        article = self.get_article(slug)

        serializer = CommentWriteSerializer(
            data=request.data,
            context={
                "request": request,
                "article": article,
                "view":    self,
            },
        )
        serializer.is_valid(raise_exception=True)

        comment = serializer.save(
            article  = article,
            status   = CommentStatus.PENDING,
            ip_hash  = Comment.hash_ip(_get_client_ip(request)),
        )

        logger.info(
            "Comment submitted: article=%s author=%s pk=%s",
            slug,
            comment.author_name,
            comment.pk,
        )

        return Response(
            {
                "detail": "Your comment has been submitted and is awaiting moderation.",
                "id":     comment.pk,
            },
            status=status.HTTP_201_CREATED,
        )


class ModerationListView(generics.ListAPIView):
    """
    GET /api/v1/moderation/comments/

    Returns the full moderation queue. Supports filtering by status.
    Requires Moderator or above.

    ?status=pending   — default, unreviewed comments
    ?status=approved
    ?status=rejected
    """

    serializer_class   = CommentModerationSerializer
    permission_classes = [IsAuthenticated, IsModeratorOrAbove]
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        filter_status = self.request.query_params.get("status", "pending")
        valid_statuses = [s.value for s in CommentStatus]
        if filter_status not in valid_statuses:
            filter_status = "pending"

        return (
            Comment.objects
            .filter(status=filter_status)
            .select_related("article")
            .order_by("created_at")
        )


class ModerationActionView(APIView):
    """
    PATCH /api/v1/moderation/comments/<id>/

    Approve or reject a single comment.
    Requires Moderator or above.

    Body: { "action": "approve" } or { "action": "reject" }
    """

    permission_classes = [IsAuthenticated, IsModeratorOrAbove]

    def patch(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)

        serializer = ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]

        if action == "approve":
            comment.status = CommentStatus.APPROVED
            message = "Comment approved and is now visible to readers."
        else:
            comment.status = CommentStatus.REJECTED
            message = "Comment rejected and is now hidden from readers."

        comment.save(update_fields=["status", "updated_at"])

        logger.info(
            "Comment pk=%s %sd by user pk=%s.",
            comment.pk,
            action,
            request.user.pk,
        )

        return Response({
            "detail": message,
            "id":     comment.pk,
            "status": comment.status,
        })
