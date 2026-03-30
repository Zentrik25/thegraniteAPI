"""
serializers.py — DRF serializers for The Granite Post articles API.

Three tiers:
  ArticleListSerializer   — lightweight feed payload (no body)
  ArticleDetailSerializer — full article with all SEO/OG fields
  ArticleWriteSerializer  — validated input for create / update

Taxonomy:
  CategorySerializer
  TagSerializer
"""

from rest_framework import serializers

from .models import Article, Category, Tag, TOP_STORY_MAX, TOP_STORY_MIN


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Category
        fields = ("id", "name", "slug", "description", "og_image_url")


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Tag
        fields = ("id", "name", "slug")


# ---------------------------------------------------------------------------
# Article — read
# ---------------------------------------------------------------------------

class ArticleListSerializer(serializers.ModelSerializer):
    """
    Minimal representation for feed / index endpoints.
    Body is excluded to keep the payload small.
    """

    category    = CategorySerializer(read_only=True)
    tags        = TagSerializer(many=True, read_only=True)
    author_name = serializers.SerializerMethodField()
    status      = serializers.CharField(source="get_status_display")

    # Computed properties from the model
    is_featured  = serializers.ReadOnlyField()
    is_top_story = serializers.ReadOnlyField()
    is_live      = serializers.ReadOnlyField()
    needs_banner = serializers.ReadOnlyField()

    class Meta:
        model  = Article
        fields = (
            "id",
            "title",
            "slug",
            "excerpt",
            "status",
            "author_name",
            "category",
            "tags",
            "is_breaking",
            "is_premium",
            "top_story_rank",
            "is_top_story",
            "is_featured",
            "featured_rank",
            "is_live",
            "needs_banner",
            "image_url",
            "image_alt",
            "published_at",
            "created_at",
            "view_count",
        )

    def get_author_name(self, obj) -> str:
        return obj.author.get_full_name() or obj.author.username


class ArticleDetailSerializer(ArticleListSerializer):
    """
    Full article payload — adds body and all SEO/OG fields.
    Used by /api/articles/<slug>/.
    """

    seo_title         = serializers.ReadOnlyField()
    seo_description   = serializers.ReadOnlyField()
    resolved_og_image = serializers.ReadOnlyField()

    class Meta(ArticleListSerializer.Meta):
        fields = ArticleListSerializer.Meta.fields + (
            "body",
            "image_caption",
            "image_credit",
            "og_title",
            "og_description",
            "og_image_url",
            "canonical_url",
            "seo_title",
            "seo_description",
            "resolved_og_image",
            "updated_at",
        )


class SectionHeroSerializer(ArticleListSerializer):
    """
    Public-safe hero article for section landing pages.

    Intentionally extends ArticleListSerializer (no ``body`` field) so premium
    and free article bodies are never exposed through the public section endpoint.
    ``is_premium`` is inherited from ArticleListSerializer so the frontend can
    render a paywall badge and teaser CTA without receiving gated content.
    """

    class Meta(ArticleListSerializer.Meta):
        pass


# ---------------------------------------------------------------------------
# Article — write
# ---------------------------------------------------------------------------

class ArticleWriteSerializer(serializers.ModelSerializer):
    """
    Validated input for POST /api/articles/ and PATCH /api/articles/<slug>/.

    - author is injected from request.user in the view.
    - slug and published_at are read-only; managed by the model.
    """

    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model  = Article
        fields = (
            "title",
            "excerpt",
            "body",
            "status",
            "category",
            "tags",
            "is_breaking",
            "top_story_rank",
            "featured_rank",
            "image_url",
            "image_alt",
            "image_caption",
            "image_credit",
            "og_title",
            "og_description",
            "og_image_url",
            "canonical_url",
        )
        read_only_fields = ("slug", "published_at")

    def validate_top_story_rank(self, value):
        if value is not None and not (TOP_STORY_MIN <= value <= TOP_STORY_MAX):
            raise serializers.ValidationError(
                f"top_story_rank must be between {TOP_STORY_MIN} and {TOP_STORY_MAX}."
            )
        return value

    def validate_og_description(self, value: str) -> str:
        if len(value) > 160:
            raise serializers.ValidationError(
                "og_description must be 160 characters or fewer."
            )
        return value

    def validate(self, attrs):
        # A category is required before an article can go live.
        if attrs.get("status") == "published" and not attrs.get("category"):
            raise serializers.ValidationError(
                {"category": "A category is required before publishing."}
            )
        return attrs

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        article = Article.objects.create(**validated_data)
        article.tags.set(tags)
        return article

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        return instance


# ---------------------------------------------------------------------------
# Top story grid serializer — used by the top story grid endpoint
# ---------------------------------------------------------------------------

class TopStoryGridSerializer(serializers.Serializer):
    """
    Represents the full 6-slot top story grid.
    Empty slots are returned as null so the frontend always receives
    exactly 6 entries and can render placeholder cards.
    """

    rank    = serializers.IntegerField()
    article = ArticleListSerializer(allow_null=True)
