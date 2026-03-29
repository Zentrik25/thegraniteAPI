from django.contrib import admin
from django.utils.html import format_html

from .models import MediaAsset


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):

    list_display = (
        "thumbnail_preview",
        "original_filename",
        "dimensions",
        "size_display",
        "uploaded_by",
        "created_at",
    )
    list_filter    = ("created_at",)
    search_fields  = ("original_filename", "alt_text", "credit", "uploaded_by__username")
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "url", "width", "height", "size_bytes",
        "original_filename", "uploaded_by", "created_at",
        "image_preview",
    )

    fieldsets = (
        ("File", {
            "fields": ("file", "url", "image_preview"),
        }),
        ("Metadata", {
            "fields": ("alt_text", "caption", "credit"),
        }),
        ("Technical", {
            "fields": ("width", "height", "size_bytes", "original_filename"),
            "classes": ("collapse",),
        }),
        ("Audit", {
            "fields": ("uploaded_by", "created_at"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request) -> bool:
        return False

    @admin.display(description="Preview")
    def thumbnail_preview(self, obj):
        if obj.url:
            return format_html(
                '<img src="{}" style="height:48px;width:auto;'
                'border-radius:4px;object-fit:cover;" />',
                obj.url,
            )
        return "—"

    @admin.display(description="Dimensions")
    def dimensions(self, obj):
        if obj.width and obj.height:
            return f"{obj.width} × {obj.height}px"
        return "—"

    @admin.display(description="Size")
    def size_display(self, obj):
        if obj.size_bytes:
            return f"{obj.size_mb}MB"
        return "—"

    @admin.display(description="Image")
    def image_preview(self, obj):
        if obj.url:
            return format_html(
                '<img src="{}" style="max-width:600px;max-height:400px;'
                'border-radius:6px;object-fit:contain;" />',
                obj.url,
            )
        return "No image."
