"""
views.py — API views for reader accounts.

All authenticated reader endpoints declare:
    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

Staff JWTs (token_type="access", user_id claim) are rejected by
ReaderJWTAuthentication because the token_type mismatch causes TokenError.
Reader JWTs are rejected by the global JWTAuthentication on staff endpoints
for the same reason.

Endpoint map:
  POST   /accounts/register/
  GET    /accounts/verify-email/?token=
  POST   /accounts/login/
  POST   /accounts/logout/
  POST   /accounts/token/refresh/
  GET    /accounts/me/
  PATCH  /accounts/me/
  POST   /accounts/change-password/
  POST   /accounts/forgot-password/
  POST   /accounts/reset-password/
  GET    /accounts/bookmarks/
  POST   /accounts/bookmarks/
  DELETE /accounts/bookmarks/<article-slug>/
  GET    /accounts/history/
  POST   /accounts/history/
  DELETE /accounts/history/
"""

import logging
import secrets
import uuid
from datetime import timedelta

from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.logging_utils import _mask_email
from core.pagination import StandardResultsPagination

from .authentication import ReaderJWTAuthentication, get_tokens_for_reader
from .models import BlacklistedReaderToken, Bookmark, ReadingHistory, ReaderAccount
from .permissions import IsReader
from .serializers import (
    BookmarkSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    ReaderProfileSerializer,
    ReaderProfileUpdateSerializer,
    ReadingHistorySerializer,
    RegistrationSerializer,
    ResetPasswordSerializer,
)
from .throttling import (
    ReaderLoginThrottle,
    ReaderPasswordResetThrottle,
    ReaderRegisterThrottle,
)

logger = logging.getLogger("accounts.views")


# ---------------------------------------------------------------------------
# Registration and email verification
# ---------------------------------------------------------------------------

class RegisterView(APIView):
    """
    POST /api/v1/accounts/register/

    Create a new reader account. Returns 201 with the reader profile.
    Queues a verification email; login is blocked until the email is verified.

    Rate limited: 5 registrations per IP per hour.
    """

    authentication_classes = []
    permission_classes     = [AllowAny]
    throttle_classes       = [ReaderRegisterThrottle]

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reader = serializer.save()

        # Persist expiry BEFORE queuing so the worker always reads a valid timestamp.
        reader.email_verification_token_expires = timezone.now() + timedelta(hours=1)
        reader.save(update_fields=["email_verification_token_expires"])

        from .tasks import send_verification_email
        try:
            send_verification_email.apply_async(args=[str(reader.id)], queue="slow")
        except Exception:
            # Broker unavailable — account is created; email will need to be resent.
            logger.error(
                "Could not queue verification email for reader pk=%s — broker unreachable.",
                reader.id,
            )

        logger.info(
            "Reader registered: pk=%s username=%s email=%s",
            reader.id, reader.username, _mask_email(reader.email),
        )

        return Response(
            ReaderProfileSerializer(reader).data,
            status=status.HTTP_201_CREATED,
        )


class ResendVerificationView(APIView):
    """
    POST /api/v1/accounts/resend-verification/

    Re-queue the verification email for an unverified account.
    Always returns 202 regardless of whether the email exists — prevents enumeration.
    Rate limited: 3 requests per IP per hour.
    """

    authentication_classes = []
    permission_classes     = [AllowAny]
    throttle_classes       = [ReaderPasswordResetThrottle]

    _RESPONSE = {"detail": "If an unverified account exists for this email, a new code has been sent."}

    def post(self, request):
        email = request.data.get("email", "").lower().strip()

        if not email:
            return Response(
                {"detail": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            reader = ReaderAccount.objects.get(
                email=email,
                is_email_verified=False,
                is_active=True,
            )
        except ReaderAccount.DoesNotExist:
            return Response(self._RESPONSE, status=status.HTTP_202_ACCEPTED)

        # Regenerate code and reset expiry.
        reader.email_verification_token = f"{secrets.randbelow(900000) + 100000}"
        reader.email_verification_token_expires = timezone.now() + timedelta(hours=1)
        reader.save(update_fields=["email_verification_token", "email_verification_token_expires"])

        from .tasks import send_verification_email
        try:
            send_verification_email.apply_async(args=[str(reader.id)], queue="slow")
        except Exception:
            logger.error(
                "Could not queue resend verification email for reader pk=%s — broker unreachable.",
                reader.id,
            )

        logger.info(
            "Verification code resent: pk=%s email=%s", reader.id, _mask_email(reader.email)
        )

        return Response(self._RESPONSE, status=status.HTTP_202_ACCEPTED)


class VerifyEmailView(APIView):
    """
    POST /api/v1/accounts/verify-email/

    Verifies the reader's email using the 6-digit code sent to their inbox.
    Body: { "email": "...", "code": "123456" }
    Rate limited to prevent brute-force against the 6-digit code space.
    """

    authentication_classes = []
    permission_classes     = [AllowAny]
    throttle_classes       = [ReaderLoginThrottle]

    def post(self, request):
        email = request.data.get("email", "").lower().strip()
        code  = request.data.get("code", "").strip()

        if not email or not code:
            return Response(
                {"detail": "Email and code are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            reader = ReaderAccount.objects.get(
                email=email,
                email_verification_token=code,
                is_email_verified=False,
            )
        except ReaderAccount.DoesNotExist:
            return Response(
                {"detail": "Invalid or already-used verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (
            reader.email_verification_token_expires is None
            or timezone.now() > reader.email_verification_token_expires
        ):
            return Response(
                {"detail": "Code has expired. Request a new one below."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reader.is_email_verified                = True
        reader.email_verification_token         = f"{secrets.randbelow(900000) + 100000}"  # rotate
        reader.email_verification_token_expires = None
        reader.save(update_fields=[
            "is_email_verified",
            "email_verification_token",
            "email_verification_token_expires",
        ])

        logger.info("Reader email verified: pk=%s email=%s", reader.id, _mask_email(reader.email))

        return Response(
            {"detail": "Email address verified. You can now log in."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Login / logout / token refresh
# ---------------------------------------------------------------------------

class LoginView(APIView):
    """
    POST /api/v1/accounts/login/

    Authenticate with email + password.
    Returns JWT access + refresh tokens and the reader profile on success.

    Rate limited: 10 attempts per IP per hour.
    """

    authentication_classes = []
    permission_classes     = [AllowAny]
    throttle_classes       = [ReaderLoginThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email    = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        try:
            reader = ReaderAccount.objects.get(email=email)
        except ReaderAccount.DoesNotExist:
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not reader.check_password(password):
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not reader.is_active:
            return Response(
                {"detail": "This account has been deactivated."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not reader.is_email_verified:
            return Response(
                {"detail": "Please verify your email address before logging in."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tokens = get_tokens_for_reader(reader)

        # Stamp last_login atomically.
        ReaderAccount.objects.filter(pk=reader.pk).update(last_login=timezone.now())
        reader.refresh_from_db(fields=["last_login"])

        logger.info("Reader logged in: pk=%s email=%s", reader.id, _mask_email(reader.email))

        return Response(
            {**tokens, "reader": ReaderProfileSerializer(reader).data},
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """
    POST /api/v1/accounts/logout/

    Blacklists the provided refresh token.
    Body: { "refresh": "<token>" }
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    def post(self, request):
        from .authentication import ReaderRefreshToken
        from rest_framework_simplejwt.exceptions import TokenError

        raw_refresh = request.data.get("refresh", "").strip()

        if not raw_refresh:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = ReaderRefreshToken(raw_refresh)
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        jti = token.get("jti", "")
        if jti:
            BlacklistedReaderToken.objects.get_or_create(jti=jti)

        logger.info("Reader logged out: pk=%s", request.user.id)

        return Response(
            {"detail": "Logged out successfully."},
            status=status.HTTP_200_OK,
        )


class ReaderTokenRefreshView(APIView):
    """
    POST /api/v1/accounts/token/refresh/

    Exchange a valid, non-blacklisted reader refresh token for a new
    access token.  The old refresh token is blacklisted (rotation).
    Body: { "refresh": "<token>" }
    """

    authentication_classes = []
    permission_classes     = [AllowAny]
    throttle_classes       = []

    def post(self, request):
        from .authentication import ReaderRefreshToken
        from rest_framework_simplejwt.exceptions import TokenError

        raw_refresh = request.data.get("refresh", "").strip()

        if not raw_refresh:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            old_refresh = ReaderRefreshToken(raw_refresh)
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        jti = old_refresh.get("jti", "")

        if jti and BlacklistedReaderToken.objects.filter(jti=jti).exists():
            return Response(
                {"detail": "Refresh token has been revoked."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        reader_id = old_refresh.get("reader_id")

        try:
            reader = ReaderAccount.objects.get(id=reader_id, is_active=True)
        except (ReaderAccount.DoesNotExist, Exception):
            return Response(
                {"detail": "Reader account not found or inactive."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Blacklist old refresh token (rotation).
        if jti:
            BlacklistedReaderToken.objects.get_or_create(jti=jti)

        return Response(get_tokens_for_reader(reader), status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class MeView(APIView):
    """
    GET   /api/v1/accounts/me/  — retrieve own profile
    PATCH /api/v1/accounts/me/  — update display_name, avatar_url, bio
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    def get(self, request):
        return Response(ReaderProfileSerializer(request.user).data)

    def patch(self, request):
        serializer = ReaderProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        reader = serializer.save()

        logger.info("Reader profile updated: pk=%s", reader.id)

        return Response(ReaderProfileSerializer(reader).data)


class ChangePasswordView(APIView):
    """
    POST /api/v1/accounts/change-password/

    Change own password. Requires the current password for verification.
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reader           = request.user
        current_password = serializer.validated_data["current_password"]
        new_password     = serializer.validated_data["new_password"]

        if not reader.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reader.set_password(new_password)
        reader.save(update_fields=["password"])

        logger.info("Reader password changed: pk=%s", reader.id)

        return Response({"detail": "Password updated successfully."})


# ---------------------------------------------------------------------------
# Password reset (unauthenticated flow)
# ---------------------------------------------------------------------------

class ForgotPasswordView(APIView):
    """
    POST /api/v1/accounts/forgot-password/

    Request a password reset email. Always returns 202 whether the email
    exists or not — prevents email enumeration attacks.

    Rate limited: 3 requests per IP per hour.
    """

    authentication_classes = []
    permission_classes     = [AllowAny]
    throttle_classes       = [ReaderPasswordResetThrottle]

    _RESPONSE = {"detail": "If an account exists for this email, a reset link has been sent."}

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        try:
            reader = ReaderAccount.objects.get(email=email, is_active=True)
        except ReaderAccount.DoesNotExist:
            return Response(self._RESPONSE, status=status.HTTP_202_ACCEPTED)

        reader.password_reset_token         = uuid.uuid4()
        reader.password_reset_token_expires = timezone.now() + timedelta(hours=1)
        reader.save(
            update_fields=["password_reset_token", "password_reset_token_expires"]
        )

        from .tasks import send_password_reset_email
        send_password_reset_email.apply_async(args=[str(reader.id)], queue="slow")

        logger.info(
            "Password reset requested: pk=%s email=%s", reader.id, _mask_email(reader.email)
        )

        return Response(self._RESPONSE, status=status.HTTP_202_ACCEPTED)


class ResetPasswordView(APIView):
    """
    POST /api/v1/accounts/reset-password/

    Reset password using the token from the reset email.
    The token expires after 1 hour.
    Body: { "token": "<uuid>", "password": "<new>" }
    """

    authentication_classes = []
    permission_classes     = [AllowAny]
    throttle_classes       = []

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token_uuid   = serializer.validated_data["token"]
        new_password = serializer.validated_data["password"]

        try:
            reader = ReaderAccount.objects.get(
                password_reset_token=token_uuid,
                is_active=True,
            )
        except ReaderAccount.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired password reset token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (
            reader.password_reset_token_expires is None
            or timezone.now() > reader.password_reset_token_expires
        ):
            return Response(
                {"detail": "Password reset token has expired. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reader.set_password(new_password)
        reader.password_reset_token         = None
        reader.password_reset_token_expires = None
        reader.save(
            update_fields=["password", "password_reset_token", "password_reset_token_expires"]
        )

        logger.info("Reader password reset: pk=%s email=%s", reader.id, _mask_email(reader.email))

        return Response({"detail": "Password has been reset. You can now log in."})


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------

class BookmarkListCreateView(APIView):
    """
    GET  /api/v1/accounts/bookmarks/  — list own bookmarks (paginated)
    POST /api/v1/accounts/bookmarks/  — add a bookmark by article_slug
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]
    pagination_class       = StandardResultsPagination

    def get(self, request):
        bookmarks = (
            Bookmark.objects
            .filter(reader=request.user)
            .select_related("article")
            .order_by("-created_at")
        )

        paginator  = self.pagination_class()
        page       = paginator.paginate_queryset(bookmarks, request)
        serializer = BookmarkSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = BookmarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        article = serializer.validated_data["article_slug"]   # Article instance

        if Bookmark.objects.filter(reader=request.user, article=article).exists():
            return Response(
                {"detail": "You have already bookmarked this article."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            bookmark = Bookmark.objects.create(reader=request.user, article=article)
        except IntegrityError:
            return Response(
                {"detail": "You have already bookmarked this article."},
                status=status.HTTP_409_CONFLICT,
            )

        cache.delete(f"accounts:bookmarks:count:{request.user.id}")

        logger.info(
            "Bookmark added: reader_pk=%s article_id=%s",
            request.user.id, bookmark.article_id,
        )

        return Response(
            BookmarkSerializer(bookmark).data,
            status=status.HTTP_201_CREATED,
        )


class BookmarkDeleteView(APIView):
    """
    DELETE /api/v1/accounts/bookmarks/<slug>/

    Remove a bookmark by article slug. Idempotent — returns 200 even if
    the bookmark did not exist.
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    def delete(self, request, slug):
        deleted, _ = Bookmark.objects.filter(
            reader        = request.user,
            article__slug = slug,
        ).delete()

        if deleted:
            cache.delete(f"accounts:bookmarks:count:{request.user.id}")
            logger.info(
                "Bookmark removed: reader_pk=%s slug=%s",
                request.user.id, slug,
            )

        return Response(
            {"detail": "Bookmark removed." if deleted else "Bookmark not found."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Reading history
# ---------------------------------------------------------------------------

class ReadingHistoryView(APIView):
    """
    GET    /api/v1/accounts/history/  — paginated reading history
    POST   /api/v1/accounts/history/  — record an article read
    DELETE /api/v1/accounts/history/  — clear all reading history
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]
    pagination_class       = StandardResultsPagination

    def get(self, request):
        history = (
            ReadingHistory.objects
            .filter(reader=request.user)
            .select_related("article")
            .order_by("-read_at")
        )

        paginator  = self.pagination_class()
        page       = paginator.paginate_queryset(history, request)
        serializer = ReadingHistorySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = ReadingHistorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        article = serializer.validated_data["article_slug"]   # Article instance

        entry, created = ReadingHistory.objects.get_or_create(
            reader  = request.user,
            article = article,
        )

        if not created:
            # Atomic increment — avoids lost-update races.
            ReadingHistory.objects.filter(pk=entry.pk).update(
                read_count = F("read_count") + 1,
                read_at    = timezone.now(),
            )
            entry.refresh_from_db()

        cache.delete(f"accounts:history:{request.user.id}")

        return Response(
            ReadingHistorySerializer(entry).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        deleted, _ = ReadingHistory.objects.filter(reader=request.user).delete()

        cache.delete(f"accounts:history:{request.user.id}")

        logger.info(
            "Reading history cleared: reader_pk=%s count=%d",
            request.user.id, deleted,
        )

        return Response(
            {"detail": f"Reading history cleared ({deleted} entries removed)."},
            status=status.HTTP_200_OK,
        )
