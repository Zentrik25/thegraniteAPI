from rest_framework import serializers

from .models import Section


class SectionSerializer(serializers.ModelSerializer):
    """
    Lightweight section for navigation lists.
    Used by GET /api/v1/sections/
    Fast to serialise — no nested articles.
    """

    article_count  = serializers.ReadOnlyField()
    category_count = serializers.ReadOnlyField()

    class Meta:
        model  = Section
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "og_image_url",
            "display_order",
            "is_primary",
            "article_count",
            "category_count",
        )


class SectionDetailSerializer(SectionSerializer):
    """
    Full section for landing pages.
    Used by GET /api/v1/sections/<slug>/

    Returns:
      hero_article — the featured/pinned article for the hero slot
      categories   — sub-categories for filtering tabs
      articles     — 20 most recent published articles
    """

    hero_article = serializers.SerializerMethodField()
    categories   = serializers.SerializerMethodField()
    articles     = serializers.SerializerMethodField()

    class Meta(SectionSerializer.Meta):
        fields = SectionSerializer.Meta.fields + (
            "hero_article",
            "categories",
            "articles",
        )

    def get_hero_article(self, obj):
        from articles.serializers import ArticleDetailSerializer
        hero = obj.get_hero_article()
        if hero:
            return ArticleDetailSerializer(
                hero, context=self.context
            ).data
        return None

    def get_categories(self, obj):
        from articles.serializers import CategorySerializer
        return CategorySerializer(
            obj.categories.all(),
            many=True,
            context=self.context,
        ).data

    def get_articles(self, obj):
        from articles.serializers import ArticleListSerializer
        articles = obj.get_latest_articles(n=20)
        return ArticleListSerializer(
            articles,
            many=True,
            context=self.context,
        ).data


class SectionWriteSerializer(serializers.ModelSerializer):
    """
    Input for creating and updating sections.
    Slug is auto-generated from name — not writable.
    Only Editors and above can use this serializer.
    """

    class Meta:
        model  = Section
        fields = (
            "name",
            "description",
            "og_image_url",
            "display_order",
            "is_active",
            "is_primary",
            "featured_article",
        )

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Section name cannot be empty.")
        return value

    def validate_display_order(self, value: int) -> int:
        if value < 0:
            raise serializers.ValidationError(
                "Display order must be 0 or greater."
            )
        return value