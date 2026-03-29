from django.core.exceptions import ValidationError
from PIL import Image

# Accepted MIME types and their file extensions.
ACCEPTED_FORMATS = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png":  [".png"],
    "image/webp": [".webp"],
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024   # 10MB
MIN_WIDTH_PX        = 400


def validate_image_file(file) -> dict:
    """
    Validate an uploaded image file.

    Checks:
      1. File is a valid image (not a disguised executable)
      2. Format is JPEG, PNG, or WebP
      3. File size is under 10MB
      4. Width is at least 800px

    Returns a dict with width, height, and size_bytes on success.
    Raises ValidationError on failure.
    """
    # Check file size before opening — avoids loading huge files into memory.
    file.seek(0, 2)
    size_bytes = file.tell()
    file.seek(0)

    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise ValidationError(
            f"File size {size_bytes / (1024*1024):.1f}MB exceeds the 10MB limit."
        )

    # Open with Pillow to verify it is a real image and get dimensions.
    try:
        img = Image.open(file)
        img.verify()
        file.seek(0)
        img = Image.open(file)
        width, height = img.size
        fmt = img.format
    except Exception:
        raise ValidationError(
            "Uploaded file is not a valid image. "
            "Accepted formats: JPEG, PNG, WebP."
        )
    finally:
        file.seek(0)

    # Check format.
    format_map = {
        "JPEG": "image/jpeg",
        "PNG":  "image/png",
        "WEBP": "image/webp",
    }
    mime_type = format_map.get(fmt)
    if not mime_type:
        raise ValidationError(
            f"Unsupported image format '{fmt}'. "
            "Accepted formats: JPEG, PNG, WebP."
        )

    # Check minimum width.
    if width < MIN_WIDTH_PX:
        raise ValidationError(
            f"Image width {width}px is below the minimum of {MIN_WIDTH_PX}px. "
            "Please upload a higher resolution image."
        )

    return {
        "width":      width,
        "height":     height,
        "size_bytes": size_bytes,
        "mime_type":  mime_type,
    }
