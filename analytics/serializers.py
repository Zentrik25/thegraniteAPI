from rest_framework import serializers


class ViewRecordedSerializer(serializers.Serializer):
    """Response body for POST /api/v1/analytics/articles/<slug>/view/"""

    article_slug = serializers.CharField()
    view_count   = serializers.IntegerField()
    recorded     = serializers.BooleanField(
        help_text="True if this request was counted. "
                  "False if it was a duplicate (same IP, same article, same day)."
    )


class TrendingArticleSerializer(serializers.Serializer):
    """One entry in the trending articles list."""

    rank       = serializers.IntegerField()
    view_count = serializers.IntegerField()
    article    = serializers.DictField()
