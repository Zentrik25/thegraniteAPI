from rest_framework import serializers

from .models import Comment, CommentStatus


class CommentPublicSerializer(serializers.ModelSerializer):
    """
    Public-facing comment serializer.
    Never exposes author_email or ip_hash.
    Includes approved replies nested under top-level comments.
    """

    replies = serializers.SerializerMethodField()

    class Meta:
        model  = Comment
        fields = (
            "id",
            "author_name",
            "body",
            "created_at",
            "is_reply",
            "parent",
            "replies",
        )

    def get_replies(self, obj):
        if obj.is_reply:
            return []
        approved_replies = obj.replies.filter(
            status=CommentStatus.APPROVED
        ).order_by("created_at")
        return CommentPublicSerializer(approved_replies, many=True).data


class CommentWriteSerializer(serializers.ModelSerializer):
    """
    Input serializer for submitting a new comment.
    Readers provide name, email, body, and optionally a parent comment id.
    """

    class Meta:
        model  = Comment
        fields = (
            "author_name",
            "author_email",
            "body",
            "parent",
        )

    def validate_parent(self, value):
        if value is None:
            return value

        # Reject replies to replies — one level deep only.
        if value.parent_id is not None:
            raise serializers.ValidationError(
                "You cannot reply to a reply. "
                "Replies are only allowed on top-level comments."
            )

        # Parent comment must belong to the same article.
        view    = self.context.get("view")
        article = self.context.get("article")
        if article and value.article_id != article.pk:
            raise serializers.ValidationError(
                "Parent comment does not belong to this article."
            )

        # Parent must be approved — no replies to pending or rejected comments.
        if value.status != CommentStatus.APPROVED:
            raise serializers.ValidationError(
                "You can only reply to approved comments."
            )

        return value

    def validate_body(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError(
                "Comment must be at least 2 characters."
            )
        if len(value) > 2000:
            raise serializers.ValidationError(
                "Comment must be 2000 characters or fewer."
            )
        return value


class CommentModerationSerializer(serializers.ModelSerializer):
    """
    Full comment detail for the moderation queue.
    Includes author_email for moderator review.
    Never returned on public endpoints.
    """

    article_title = serializers.CharField(
        source="article.title",
        read_only=True,
    )
    article_slug = serializers.CharField(
        source="article.slug",
        read_only=True,
    )

    class Meta:
        model  = Comment
        fields = (
            "id",
            "article_title",
            "article_slug",
            "parent",
            "author_name",
            "author_email",
            "body",
            "status",
            "ip_hash",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "article_title",
            "article_slug",
            "parent",
            "author_name",
            "author_email",
            "body",
            "ip_hash",
            "created_at",
            "updated_at",
        )


class ModerationActionSerializer(serializers.Serializer):
    """Input for PATCH /api/v1/moderation/comments/<id>/"""

    action = serializers.ChoiceField(
        choices=["approve", "reject"],
        help_text="approve — makes the comment visible. reject — hides it.",
    )
