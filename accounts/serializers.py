"""
serializers.py — DRF serializers for reader accounts.

Serializer inventory:
  RegistrationSerializer        POST /accounts/register/
  LoginSerializer               POST /accounts/login/
  ReaderProfileSerializer       GET  /accounts/me/
  ReaderProfileUpdateSerializer PATCH /accounts/me/
  ChangePasswordSerializer      POST /accounts/change-password/
  ForgotPasswordSerializer      POST /accounts/forgot-password/
  ResetPasswordSerializer       POST /accounts/reset-password/
  BookmarkSerializer            GET/POST /accounts/bookmarks/
  ReadingHistorySerializer      GET/POST /accounts/history/
"""

import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from articles.models import Article, PublishStatus

from .models import Bookmark, ReaderAccount, ReadingHistory


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

def _validate_username(value: str) -> str:
    """Enforce format: letters, digits, underscores, hyphens; 3–50 chars."""
    if not re.match(r"^[\w\-]{3,50}$", value):
        raise serializers.ValidationError(
            "Username may only contain letters, digits, underscores, and "
            "hyphens (3–50 characters)."
        )
    return value.lower()


def _validate_strong_password(value: str) -> str:
    """Run Django's built-in password validators."""
    try:
        validate_password(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages)) from exc
    return value


# ---------------------------------------------------------------------------
# Auth serializers
# ---------------------------------------------------------------------------

class RegistrationSerializer(serializers.Serializer):
    """
    Input for POST /api/v1/accounts/register/

    Validates uniqueness of email and username, enforces password strength,
    and creates the ReaderAccount with is_email_verified=False.
    """

    email        = serializers.EmailField()
    username     = serializers.CharField(max_length=50)
    password     = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    display_name = serializers.CharField(max_length=100, required=False, default="")

    def validate_email(self, value: str) -> str:
        value = value.lower().strip()
        if ReaderAccount.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "An account with this email address already exists."
            )
        return value

    def validate_username(self, value: str) -> str:
        value = _validate_username(value)
        if ReaderAccount.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_password(self, value: str) -> str:
        return _validate_strong_password(value)

    def create(self, validated_data: dict) -> ReaderAccount:
        reader = ReaderAccount(
            email        = validated_data["email"],
            username     = validated_data["username"],
            display_name = validated_data.get("display_name", ""),
        )
        reader.set_password(validated_data["password"])
        reader.save()
        return reader


class LoginSerializer(serializers.Serializer):
    """Input for POST /api/v1/accounts/login/"""

    email    = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


# ---------------------------------------------------------------------------
# Profile serializers
# ---------------------------------------------------------------------------

class ReaderProfileSerializer(serializers.ModelSerializer):
    """
    Read-only profile for GET /api/v1/accounts/me/ and login response.
    Never exposes password, tokens, or reset fields.
    """

    public_name    = serializers.ReadOnlyField()
    bookmark_count = serializers.SerializerMethodField()

    class Meta:
        model  = ReaderAccount
        fields = (
            "id",
            "email",
            "username",
            "display_name",
            "public_name",
            "avatar_url",
            "bio",
            "is_email_verified",
            "date_joined",
            "last_login",
            "bookmark_count",
        )
        read_only_fields = fields

    def get_bookmark_count(self, obj) -> int:
        from django.core.cache import cache
        key   = f"accounts:bookmarks:count:{obj.id}"
        count = cache.get(key)
        if count is None:
            count = obj.bookmarks.count()
            cache.set(key, count, 60)
        return count


class ReaderProfileUpdateSerializer(serializers.ModelSerializer):
    """Input for PATCH /api/v1/accounts/me/ — only mutable profile fields."""

    class Meta:
        model  = ReaderAccount
        fields = (
            "display_name",
            "avatar_url",
            "bio",
        )

    def validate_bio(self, value: str) -> str:
        if len(value) > 500:
            raise serializers.ValidationError("Bio must be 500 characters or fewer.")
        return value


# ---------------------------------------------------------------------------
# Password serializers
# ---------------------------------------------------------------------------

class ChangePasswordSerializer(serializers.Serializer):
    """Input for POST /api/v1/accounts/change-password/"""

    current_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    new_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_new_password(self, value: str) -> str:
        return _validate_strong_password(value)


class ForgotPasswordSerializer(serializers.Serializer):
    """Input for POST /api/v1/accounts/forgot-password/"""

    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class ResetPasswordSerializer(serializers.Serializer):
    """Input for POST /api/v1/accounts/reset-password/"""

    token    = serializers.UUIDField()
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_password(self, value: str) -> str:
        return _validate_strong_password(value)


# ---------------------------------------------------------------------------
# Bookmark and history serializers
# ---------------------------------------------------------------------------

class ArticleMinimalSerializer(serializers.ModelSerializer):
    """
    Minimal article representation nested inside bookmark and history responses.
    Kept local to avoid circular imports with articles.serializers.
    """

    class Meta:
        model  = Article
        fields = (
            "id",
            "title",
            "slug",
            "excerpt",
            "image_url",
            "published_at",
        )
        read_only_fields = fields


class BookmarkSerializer(serializers.ModelSerializer):
    """
    Bookmark read/write serializer.

    Read  — ``article`` is a nested ArticleMinimalSerializer.
    Write — ``article_slug`` (write-only) resolves to a published Article.
            validate_article_slug returns the Article instance, which the
            view accesses as ``serializer.validated_data["article_slug"]``.
    """

    article      = ArticleMinimalSerializer(read_only=True)
    article_slug = serializers.SlugField(write_only=True)

    class Meta:
        model  = Bookmark
        fields = (
            "id",
            "article",
            "article_slug",
            "created_at",
        )
        read_only_fields = ("id", "article", "created_at")

    def validate_article_slug(self, value: str) -> Article:
        try:
            return Article.objects.get(slug=value, status=PublishStatus.PUBLISHED)
        except Article.DoesNotExist:
            raise serializers.ValidationError("Article not found or is not published.")


class ReadingHistorySerializer(serializers.ModelSerializer):
    """
    Reading history read/write serializer.

    Read  — ``article`` is nested.
    Write — ``article_slug`` resolves to a published Article instance in
            ``validated_data["article_slug"]``. The view handles get_or_create
            and F()-based read_count increments.
    """

    article      = ArticleMinimalSerializer(read_only=True)
    article_slug = serializers.SlugField(write_only=True)

    class Meta:
        model  = ReadingHistory
        fields = (
            "id",
            "article",
            "article_slug",
            "read_at",
            "read_count",
        )
        read_only_fields = ("id", "article", "read_at", "read_count")

    def validate_article_slug(self, value: str) -> Article:
        try:
            return Article.objects.get(slug=value, status=PublishStatus.PUBLISHED)
        except Article.DoesNotExist:
            raise serializers.ValidationError("Article not found or is not published.")
