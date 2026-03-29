from rest_framework import serializers

from .models import MediaAsset


class MediaAssetSerializer(serializers.ModelSerializer):
    """
    Full media asset representation.
    Returned after upload and in list/detail views.
    """

    uploaded_by_name = serializers.SerializerMethodField()
    aspect_ratio     = serializers.ReadOnlyField()
    size_kb          = serializers.ReadOnlyField()
    size_mb          = serializers.ReadOnlyField()

    class Meta:
        model  = MediaAsset
        fields = (
            "id",
            "url",
            "alt_text",
            "caption",
            "credit",
            "width",
            "height",
            "aspect_ratio",
            "size_bytes",
            "size_kb",
            "size_mb",
            "original_filename",
            "uploaded_by_name",
            "created_at",
        )

    def get_uploaded_by_name(self, obj) -> str:
        if obj.uploaded_by:
            return obj.uploaded_by.byline
        return ""


class MediaUploadSerializer(serializers.Serializer):
    """
    Input serializer for POST /api/v1/media/

    Accepts a file plus optional metadata.
    Validation (format, size, dimensions) happens in the view
    using validators.validate_image_file().
    """

    file     = serializers.ImageField(
        help_text="Image file. Accepted: JPEG, PNG, WebP. Max: 10MB. Min width: 800px.",
    )
    alt_text = serializers.CharField(
        max_length=255,
        required=False,
        default="",
        help_text="Alt text for accessibility.",
    )
    caption  = serializers.CharField(
        max_length=255,
        required=False,
        default="",
    )
    credit   = serializers.CharField(
        max_length=255,
        required=False,
        default="",
        help_text="Photographer or agency credit.",
    )
