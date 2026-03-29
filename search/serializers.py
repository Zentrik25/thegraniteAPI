from rest_framework import serializers

from articles.serializers import ArticleListSerializer


class SearchResultSerializer(serializers.Serializer):
    """
    A single search result with relevance rank.
    Wraps ArticleListSerializer with an added rank score.
    """

    rank    = serializers.FloatField(
        help_text="Relevance score. Higher means more relevant."
    )
    article = ArticleListSerializer()


class SearchResponseSerializer(serializers.Serializer):
    """
    Full search response envelope.
    """

    query        = serializers.CharField()
    count        = serializers.IntegerField()
    total_pages  = serializers.IntegerField()
    current_page = serializers.IntegerField()
    next         = serializers.CharField(allow_null=True)
    previous     = serializers.CharField(allow_null=True)
    results      = SearchResultSerializer(many=True)
