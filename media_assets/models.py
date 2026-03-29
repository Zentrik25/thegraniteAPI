import os

from django.conf import settings
from django.db import models
from django.utils import timezone


def upload_to(instance, filename):
    """
    Organise uploads by year/month so the media folder does not
    become a flat directory with thousands of files.
    Example: uploads/2026/03/filename.jpg
    """
    now = timezone.now()
    ext = os.path.splitext(filename)[1].lower()
    return f"uploads/{now.year}/{now.month:02d}/{instance.pk or 'new'}{ext}"


class MediaAsset(models.Model):
    """
    A single uploaded image asset.

    Articles reference media assets via their url field —
    editors copy the url into Article.image_url.
    There is no FK between Article and MediaAsset intentionally.
    This keeps articles portable and avoids cascade deletes
    breaking published article images.

    Dimensions
    ----------
    Minimum width:  800px
    Maximum size:   10MB
    Formats:        JPEG, PNG, WebP

    Standard sizes for The Granite Post:
      Hero / lead image:     1200 x 675  (16:9)
      Top story slots 2-6:    800 x 450  (16:9)
      Article thumbnail:      400 x 225  (16:9)
      Author avatar:          400 x 400  (1:1)
      Open Graph share:      1200 x 630  (1.91:1)
      Category banner:       1600 x 400  (4:1)
    """

    file         = models.ImageField(upload_to=upload_to)
    url          = models.URLField(
        blank=True,
        help_text="Public CDN URL. Populated after upload. "
                  "Paste this into Article.image_url.",
    )
    alt_text     = models.CharField(
        max_length=255,
        blank=True,
        help_text="Alt text for accessibility. Describe the image content.",
    )
    caption      = models.CharField(max_length=255, blank=True)
    credit       = models.CharField(
        max_length=255,
        blank=True,
        help_text="Photographer or agency credit.",
    )
    width        = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Image width in pixels.",
    )
    height       = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Image height in pixels.",
    )
    size_bytes   = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes.",
    )
    original_filename = models.CharField(
        max_length=255,
        blank=True,
        help_text="Original filename as uploaded.",
    )
    uploaded_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="media_assets",
    )
    created_at   = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(
                fields=["uploaded_by", "created_at"],
                name="media_uploader_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.original_filename or f"MediaAsset {self.pk}"

    @property
    def aspect_ratio(self) -> str:
        if self.width and self.height:
            from math import gcd
            g = gcd(self.width, self.height)
            return f"{self.width // g}:{self.height // g}"
        return ""

    @property
    def size_kb(self) -> float:
        if self.size_bytes:
            return round(self.size_bytes / 1024, 1)
        return 0.0

    @property
    def size_mb(self) -> float:
        if self.size_bytes:
            return round(self.size_bytes / (1024 * 1024), 2)
        return 0.0
