import io
import os
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from .models import MediaAsset
from .validators import validate_image_file

User = get_user_model()

# Use a temp directory for media files during tests.
TEMP_MEDIA = tempfile.mkdtemp()


def make_user(username="reporter", role="author"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_image_file(
    width=1200,
    height=675,
    fmt="JPEG",
    size_mb=None,
    filename="test.jpg",
):
    """
    Create an in-memory image file for testing.
    size_mb overrides the actual image content with padding bytes
    to simulate large files.
    """
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(buf, format=fmt)

    if size_mb:
        # Pad the buffer to simulate a large file.
        buf.write(b"0" * int(size_mb * 1024 * 1024))

    buf.seek(0)
    content_type_map = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    return SimpleUploadedFile(
        filename,
        buf.read(),
        content_type=content_type_map.get(fmt, "image/jpeg"),
    )


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class ValidatorTests(TestCase):

    def test_valid_jpeg_passes(self):
        f      = make_image_file(width=1200, height=675)
        result = validate_image_file(f)
        self.assertEqual(result["width"],  1200)
        self.assertEqual(result["height"], 675)
        self.assertIn("size_bytes", result)

    def test_valid_png_passes(self):
        f      = make_image_file(width=1200, height=675, fmt="PNG", filename="test.png")
        result = validate_image_file(f)
        self.assertEqual(result["width"], 1200)

    def test_image_too_narrow_raises(self):
        from django.core.exceptions import ValidationError
        f = make_image_file(width=400, height=300)
        with self.assertRaises(ValidationError):
            validate_image_file(f)

    def test_file_too_large_raises(self):
        from django.core.exceptions import ValidationError
        buf = io.BytesIO()
        img = Image.new("RGB", (1200, 675))
        img.save(buf, format="JPEG")
        buf.write(b"0" * (11 * 1024 * 1024))
        buf.seek(0)
        f = SimpleUploadedFile("big.jpg", buf.read(), content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            validate_image_file(f)

    def test_non_image_file_raises(self):
        from django.core.exceptions import ValidationError
        f = SimpleUploadedFile(
            "test.txt",
            b"this is not an image",
            content_type="text/plain",
        )
        with self.assertRaises(ValidationError):
            validate_image_file(f)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class MediaAssetModelTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_aspect_ratio_16_9(self):
        asset = MediaAsset(width=1200, height=675)
        self.assertEqual(asset.aspect_ratio, "16:9")

    def test_aspect_ratio_1_1(self):
        asset = MediaAsset(width=400, height=400)
        self.assertEqual(asset.aspect_ratio, "1:1")

    def test_aspect_ratio_empty_without_dimensions(self):
        asset = MediaAsset()
        self.assertEqual(asset.aspect_ratio, "")

    def test_size_kb(self):
        asset = MediaAsset(size_bytes=102400)
        self.assertEqual(asset.size_kb, 100.0)

    def test_size_mb(self):
        asset = MediaAsset(size_bytes=1048576)
        self.assertEqual(asset.size_mb, 1.0)


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class MediaUploadAPITests(APITestCase):

    def setUp(self):
        self.author      = make_user("author1",   role="author")
        self.editor      = make_user("editor1",   role="editor")
        self.contributor = make_user("contrib1",  role="contributor")

    def test_upload_requires_auth(self):
        f = make_image_file()
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 401)

    def test_contributor_cannot_upload(self):
        self.client.force_authenticate(self.contributor)
        f = make_image_file()
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_author_can_upload(self):
        self.client.force_authenticate(self.author)
        f = make_image_file()
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 201)

    def test_upload_returns_url(self):
        self.client.force_authenticate(self.author)
        f = make_image_file()
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertIn("url", r.data)
        self.assertTrue(r.data["url"].startswith("http"))

    def test_upload_returns_dimensions(self):
        self.client.force_authenticate(self.author)
        f = make_image_file(width=1200, height=675)
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertEqual(r.data["width"],  1200)
        self.assertEqual(r.data["height"], 675)

    def test_upload_returns_aspect_ratio(self):
        self.client.force_authenticate(self.author)
        f = make_image_file(width=1200, height=675)
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertEqual(r.data["aspect_ratio"], "16:9")

    def test_upload_with_metadata(self):
        self.client.force_authenticate(self.author)
        f = make_image_file()
        r = self.client.post("/api/v1/media/", {
            "file":     f,
            "alt_text": "Harare skyline at sunset",
            "caption":  "The Harare CBD photographed from Kopje Hill.",
            "credit":   "Photo: Tendai Moyo",
        }, format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["alt_text"], "Harare skyline at sunset")
        self.assertEqual(r.data["credit"],   "Photo: Tendai Moyo")

    def test_image_too_narrow_returns_400(self):
        self.client.force_authenticate(self.author)
        f = make_image_file(width=400, height=300)
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_non_image_returns_400(self):
        self.client.force_authenticate(self.author)
        f = SimpleUploadedFile("doc.txt", b"not an image", content_type="text/plain")
        r = self.client.post("/api/v1/media/", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 400)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class MediaListAPITests(APITestCase):

    def setUp(self):
        self.author = make_user("author2", role="author")
        self.editor = make_user("editor2", role="editor")

    def test_list_requires_auth(self):
        r = self.client.get("/api/v1/media/")
        self.assertEqual(r.status_code, 401)

    def test_author_sees_only_own_uploads(self):
        other = make_user("other2", role="author")
        self.client.force_authenticate(self.author)
        self.client.post(
            "/api/v1/media/",
            {"file": make_image_file()},
            format="multipart",
        )
        self.client.force_authenticate(other)
        self.client.post(
            "/api/v1/media/",
            {"file": make_image_file()},
            format="multipart",
        )
        self.client.force_authenticate(self.author)
        r = self.client.get("/api/v1/media/")
        self.assertEqual(r.data["count"], 1)

    def test_editor_sees_all_uploads(self):
        self.client.force_authenticate(self.author)
        self.client.post(
            "/api/v1/media/",
            {"file": make_image_file()},
            format="multipart",
        )
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/v1/media/")
        self.assertGreaterEqual(r.data["count"], 1)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class MediaDeleteAPITests(APITestCase):

    def setUp(self):
        self.author = make_user("del_author", role="author")
        self.editor = make_user("del_editor", role="editor")
        self.other  = make_user("del_other",  role="author")

        self.client.force_authenticate(self.author)
        r = self.client.post(
            "/api/v1/media/",
            {"file": make_image_file()},
            format="multipart",
        )
        self.asset_id = r.data["id"]

    def test_uploader_can_delete_own_asset(self):
        self.client.force_authenticate(self.author)
        r = self.client.delete(f"/api/v1/media/{self.asset_id}/")
        self.assertEqual(r.status_code, 200)

    def test_other_author_cannot_delete(self):
        """Non-owner gets 404, not 403 — asset existence is not leaked."""
        self.client.force_authenticate(self.other)
        r = self.client.delete(f"/api/v1/media/{self.asset_id}/")
        self.assertEqual(r.status_code, 404)

    def test_other_author_delete_returns_404_not_403(self):
        """
        Explicitly guard the non-leak guarantee.  A 403 would confirm the
        asset ID is valid; 404 is indistinguishable from a missing record.
        """
        self.client.force_authenticate(self.other)
        r = self.client.delete(f"/api/v1/media/{self.asset_id}/")
        self.assertNotEqual(r.status_code, 403)

    def test_editor_can_delete_any_asset(self):
        self.client.force_authenticate(self.editor)
        r = self.client.delete(f"/api/v1/media/{self.asset_id}/")
        self.assertEqual(r.status_code, 200)

    def test_delete_removes_record(self):
        self.client.force_authenticate(self.author)
        self.client.delete(f"/api/v1/media/{self.asset_id}/")
        self.assertFalse(MediaAsset.objects.filter(pk=self.asset_id).exists())


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class MediaDetailAccessTests(APITestCase):
    """
    GET /api/v1/media/<id>/ — ownership guard matches list view.

    Authors must only be able to retrieve their own assets.
    Editors and above may retrieve any asset.
    """

    def setUp(self):
        self.author  = make_user("det_author", role="author")
        self.other   = make_user("det_other",  role="author")
        self.editor  = make_user("det_editor", role="editor")

        # Upload one asset as `author`
        self.client.force_authenticate(self.author)
        r = self.client.post(
            "/api/v1/media/",
            {"file": make_image_file()},
            format="multipart",
        )
        self.asset_id = r.data["id"]

    def test_owner_can_retrieve_own_asset(self):
        """Author can GET their own asset detail."""
        self.client.force_authenticate(self.author)
        r = self.client.get(f"/api/v1/media/{self.asset_id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["id"], self.asset_id)

    def test_other_author_cannot_retrieve_asset(self):
        """Another author gets 404, not a 403 that leaks existence."""
        self.client.force_authenticate(self.other)
        r = self.client.get(f"/api/v1/media/{self.asset_id}/")
        self.assertEqual(r.status_code, 404)

    def test_editor_can_retrieve_any_asset(self):
        """Editor (can_edit_any_article=True) can GET any author's asset."""
        self.client.force_authenticate(self.editor)
        r = self.client.get(f"/api/v1/media/{self.asset_id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["id"], self.asset_id)

    def test_unauthenticated_cannot_retrieve(self):
        """Unauthenticated requests are rejected."""
        self.client.force_authenticate(None)
        r = self.client.get(f"/api/v1/media/{self.asset_id}/")
        self.assertEqual(r.status_code, 401)
