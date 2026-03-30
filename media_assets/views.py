import logging
import os

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsPagination
from users.permissions import IsAuthorOrAbove, IsEditorOrAbove

from .models import MediaAsset
from .serializers import MediaAssetSerializer, MediaUploadSerializer
from .validators import validate_image_file

logger = logging.getLogger("media_assets.views")


class MediaUploadView(APIView):
    """
    GET  /api/v1/media/  — list all uploaded assets (Author and above)
    POST /api/v1/media/  — upload a new image (Author and above)

    POST accepts multipart/form-data with:
      file     — the image file (required)
      alt_text — accessibility alt text (optional)
      caption  — image caption (optional)
      credit   — photographer credit (optional)

    Validation:
      - JPEG, PNG, or WebP only
      - Max 10MB
      - Min width 800px

    After upload the response includes the url field which editors
    paste into Article.image_url.
    """

    parser_classes     = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, IsAuthorOrAbove]
    pagination_class   = StandardResultsPagination

    def get(self, request):
        assets = (
            MediaAsset.objects
            .select_related("uploaded_by")
            .order_by("-created_at")
        )

        # Non-editors only see their own uploads.
        if not request.user.can_edit_any_article:
            assets = assets.filter(uploaded_by=request.user)

        paginator   = self.pagination_class()
        page        = paginator.paginate_queryset(assets, request)
        serializer  = MediaAssetSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = MediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]

        # Validate image format, size, and minimum dimensions.
        from rest_framework.exceptions import ValidationError
        try:
            image_info = validate_image_file(uploaded_file)
        except Exception as exc:
            raise ValidationError({"file": str(exc)})

        # Build the public URL after saving.
        asset = MediaAsset(
            alt_text          = serializer.validated_data.get("alt_text", ""),
            caption           = serializer.validated_data.get("caption", ""),
            credit            = serializer.validated_data.get("credit", ""),
            width             = image_info["width"],
            height            = image_info["height"],
            size_bytes        = image_info["size_bytes"],
            original_filename = uploaded_file.name,
            uploaded_by       = request.user,
        )

        # Save the file — this triggers upload_to() to generate the path.
        asset.file = uploaded_file
        asset.save()

        # Build the absolute public URL.
        asset.url = request.build_absolute_uri(asset.file.url)
        asset.save(update_fields=["url"])

        # Queue image processing task (thumbnail generation etc).
        try:
            from core.tasks import process_image
            process_image.apply_async(args=[asset.pk], queue="slow")
        except Exception:
            pass

        logger.info(
            "Image uploaded: pk=%s filename=%s size=%s width=%s height=%s by user=%s",
            asset.pk,
            asset.original_filename,
            asset.size_bytes,
            asset.width,
            asset.height,
            request.user.pk,
        )

        return Response(
            MediaAssetSerializer(asset).data,
            status=status.HTTP_201_CREATED,
        )


class MediaDetailView(APIView):
    """
    GET    /api/v1/media/<id>/  — retrieve a single asset
    DELETE /api/v1/media/<id>/  — delete an asset

    Delete rules:
      - Uploader can delete their own assets
      - Editors and above can delete any asset
      - Deleting an asset does not affect articles that reference it
        via image_url — those are plain URL strings
    """

    permission_classes = [IsAuthenticated, IsAuthorOrAbove]

    def get(self, request, pk):
        qs = MediaAsset.objects.select_related("uploaded_by")
        # Non-editors may only retrieve their own assets — same restriction as
        # the list view.  404 is intentional: it avoids leaking asset existence
        # to other authors via a distinguishable 403 response.
        if not request.user.can_edit_any_article:
            qs = qs.filter(uploaded_by=request.user)
        asset = get_object_or_404(qs, pk=pk)
        return Response(MediaAssetSerializer(asset).data)

    def delete(self, request, pk):
        # Apply the same ownership filter used by GET so that a non-owner
        # author receives 404 rather than 403.  404 is intentional: it avoids
        # leaking asset existence to other authors via a distinguishable 403.
        qs = MediaAsset.objects.all()
        if not request.user.can_edit_any_article:
            qs = qs.filter(uploaded_by=request.user)
        asset = get_object_or_404(qs, pk=pk)

        filename = asset.original_filename
        pk_val   = asset.pk

        # Delete the file from storage.
        if asset.file:
            try:
                asset.file.delete(save=False)
            except Exception as exc:
                logger.warning(
                    "Could not delete file for asset pk=%s: %s", pk_val, exc
                )

        asset.delete()

        logger.info(
            "Media asset deleted: pk=%s filename=%s by user=%s",
            pk_val,
            filename,
            request.user.pk,
        )

        return Response(
            {"detail": f"'{filename}' has been deleted."},
            status=status.HTTP_200_OK,
        )
