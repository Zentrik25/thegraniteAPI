"""
tests.py — Comprehensive tests for the reader accounts app.

Test coverage:
  RegistrationTests         — register, duplicate email/username, weak password
  EmailVerificationTests    — verify, expired token, already-verified
  LoginTests                — success, wrong password, unverified, inactive
  TokenRefreshTests         — refresh, blacklisted token, invalid token
  LogoutTests               — blacklists refresh token
  MeTests                   — get / patch profile, unauthenticated
  ChangePasswordTests       — success, wrong current password
  ForgotPasswordTests       — enqueue reset, unknown email returns 202
  ResetPasswordTests        — success, expired token, invalid token
  BookmarkTests             — list, add, duplicate, remove, unauthenticated
  ReadingHistoryTests       — record, increment read_count, list, clear
"""

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from articles.models import Article, Category, PublishStatus

from .authentication import get_tokens_for_reader
from .models import BlacklistedReaderToken, Bookmark, ReadingHistory, ReaderAccount

StaffUser = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_reader(
    email    = "reader@example.com",
    username = "testreader",
    password = "SecurePass123!",
    verified = True,
    active   = True,
) -> ReaderAccount:
    """Create and return a ReaderAccount, optionally pre-verified."""
    reader = ReaderAccount(
        email        = email,
        username     = username,
        display_name = "Test Reader",
        is_active    = active,
    )
    reader.set_password(password)
    if verified:
        reader.is_email_verified = True
    reader.save()
    return reader


def make_staff() -> StaffUser:
    return StaffUser.objects.create_user(
        username = "staffuser",
        email    = "staff@granite.co.zw",
        password = "StaffPass123!",
        role     = "author",
    )


def make_article(title="Test Article") -> Article:
    cat = Category.objects.get_or_create(name="Test Category")[0]
    author = StaffUser.objects.filter(username="staffuser").first()
    if not author:
        author = make_staff()
    return Article.objects.create(
        title    = title,
        body     = "Article body.",
        author   = author,
        category = cat,
        status   = PublishStatus.PUBLISHED,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class RegistrationTests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()

    def test_register_returns_201(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email":    "new@example.com",
            "username": "newreader",
            "password": "SecurePass123!",
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_register_creates_unverified_account(self):
        self.client.post("/api/v1/accounts/register/", {
            "email":    "unverified@example.com",
            "username": "unverifiedreader",
            "password": "SecurePass123!",
        })
        reader = ReaderAccount.objects.get(email="unverified@example.com")
        self.assertFalse(reader.is_email_verified)

    def test_register_response_has_profile_fields(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email":        "fields@example.com",
            "username":     "fieldsreader",
            "password":     "SecurePass123!",
            "display_name": "Fields Reader",
        })
        self.assertIn("id",       r.data)
        self.assertIn("email",    r.data)
        self.assertIn("username", r.data)
        self.assertNotIn("password", r.data)

    def test_register_duplicate_email_returns_400(self):
        make_reader(email="dup@example.com", username="dupreader1")
        r = self.client.post("/api/v1/accounts/register/", {
            "email":    "dup@example.com",
            "username": "differentusername",
            "password": "SecurePass123!",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_username_returns_400(self):
        make_reader(email="first@example.com", username="duplicateuser")
        r = self.client.post("/api/v1/accounts/register/", {
            "email":    "second@example.com",
            "username": "duplicateuser",
            "password": "SecurePass123!",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_weak_password_returns_400(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email":    "weak@example.com",
            "username": "weakpassreader",
            "password": "123",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_fields_returns_400(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email": "incomplete@example.com",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_email_normalised_to_lowercase(self):
        self.client.post("/api/v1/accounts/register/", {
            "email":    "UPPER@EXAMPLE.COM",
            "username": "upperreader",
            "password": "SecurePass123!",
        })
        self.assertTrue(
            ReaderAccount.objects.filter(email="upper@example.com").exists()
        )

    def test_register_username_normalised_to_lowercase(self):
        self.client.post("/api/v1/accounts/register/", {
            "email":    "lower@example.com",
            "username": "MixedCase",
            "password": "SecurePass123!",
        })
        self.assertTrue(
            ReaderAccount.objects.filter(username="mixedcase").exists()
        )


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

class EmailVerificationTests(APITestCase):

    def setUp(self):
        self.reader = make_reader(verified=False)

    def test_verify_valid_token_returns_200(self):
        r = self.client.get(
            f"/api/v1/accounts/verify-email/"
            f"?token={self.reader.email_verification_token}"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_verify_sets_is_email_verified(self):
        self.client.get(
            f"/api/v1/accounts/verify-email/"
            f"?token={self.reader.email_verification_token}"
        )
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.is_email_verified)

    def test_verify_token_rotated_after_use(self):
        original_token = self.reader.email_verification_token
        self.client.get(f"/api/v1/accounts/verify-email/?token={original_token}")
        self.reader.refresh_from_db()
        self.assertNotEqual(self.reader.email_verification_token, original_token)

    def test_verify_already_verified_returns_400(self):
        self.reader.is_email_verified = True
        self.reader.save()
        r = self.client.get(
            f"/api/v1/accounts/verify-email/"
            f"?token={self.reader.email_verification_token}"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_invalid_token_returns_400(self):
        r = self.client.get(
            f"/api/v1/accounts/verify-email/?token={uuid.uuid4()}"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_missing_token_returns_400(self):
        r = self.client.get("/api/v1/accounts/verify-email/")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_expired_token_returns_400(self):
        # Backdate date_joined beyond the 24-hour window.
        ReaderAccount.objects.filter(pk=self.reader.pk).update(
            date_joined=timezone.now() - timedelta(hours=25)
        )
        r = self.client.get(
            f"/api/v1/accounts/verify-email/"
            f"?token={self.reader.email_verification_token}"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginTests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()
        self.reader   = make_reader(email="login@example.com", username="loginreader")
        self.password = "SecurePass123!"

    def test_login_returns_200(self):
        r = self.client.post("/api/v1/accounts/login/", {
            "email":    "login@example.com",
            "password": self.password,
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_login_returns_access_and_refresh_tokens(self):
        r = self.client.post("/api/v1/accounts/login/", {
            "email":    "login@example.com",
            "password": self.password,
        })
        self.assertIn("access",  r.data)
        self.assertIn("refresh", r.data)

    def test_login_includes_reader_profile(self):
        r = self.client.post("/api/v1/accounts/login/", {
            "email":    "login@example.com",
            "password": self.password,
        })
        self.assertIn("reader", r.data)
        self.assertEqual(r.data["reader"]["username"], "loginreader")

    def test_login_wrong_password_returns_401(self):
        r = self.client.post("/api/v1/accounts/login/", {
            "email":    "login@example.com",
            "password": "WrongPassword!",
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unknown_email_returns_401(self):
        r = self.client.post("/api/v1/accounts/login/", {
            "email":    "nobody@example.com",
            "password": self.password,
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unverified_email_returns_403(self):
        unverified = make_reader(
            email="unver@example.com", username="unverified2", verified=False
        )
        r = self.client.post("/api/v1/accounts/login/", {
            "email":    "unver@example.com",
            "password": self.password,
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_inactive_account_returns_403(self):
        inactive = make_reader(
            email="inactive@example.com", username="inactive2", active=False
        )
        r = self.client.post("/api/v1/accounts/login/", {
            "email":    "inactive@example.com",
            "password": self.password,
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_stamps_last_login(self):
        self.assertIsNone(self.reader.last_login)
        self.client.post("/api/v1/accounts/login/", {
            "email":    "login@example.com",
            "password": self.password,
        })
        self.reader.refresh_from_db()
        self.assertIsNotNone(self.reader.last_login)


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

class TokenRefreshTests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()
        self.reader = make_reader(email="refresh@example.com", username="refreshreader")
        self.tokens = get_tokens_for_reader(self.reader)

    def test_refresh_returns_new_access_token(self):
        r = self.client.post("/api/v1/accounts/token/refresh/", {
            "refresh": self.tokens["refresh"],
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("access", r.data)

    def test_refresh_blacklists_old_refresh_token(self):
        r = self.client.post("/api/v1/accounts/token/refresh/", {
            "refresh": self.tokens["refresh"],
        })
        # Second use of the same refresh token should be rejected.
        r2 = self.client.post("/api/v1/accounts/token/refresh/", {
            "refresh": self.tokens["refresh"],
        })
        self.assertEqual(r2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_invalid_token_returns_401(self):
        r = self.client.post("/api/v1/accounts/token/refresh/", {
            "refresh": "not.a.valid.token",
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_missing_token_returns_400(self):
        r = self.client.post("/api/v1/accounts/token/refresh/", {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class LogoutTests(APITestCase):

    def setUp(self):
        self.reader = make_reader(email="logout@example.com", username="logoutreader")
        self.tokens = get_tokens_for_reader(self.reader)

    def test_logout_returns_200(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/logout/", {
            "refresh": self.tokens["refresh"],
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_logout_blacklists_refresh_token(self):
        self.client.force_authenticate(self.reader)
        self.client.post("/api/v1/accounts/logout/", {
            "refresh": self.tokens["refresh"],
        })
        from .authentication import ReaderRefreshToken
        token = ReaderRefreshToken(self.tokens["refresh"])
        jti   = token.get("jti", "")
        self.assertTrue(BlacklistedReaderToken.objects.filter(jti=jti).exists())

    def test_logout_unauthenticated_returns_401(self):
        r = self.client.post("/api/v1/accounts/logout/", {
            "refresh": self.tokens["refresh"],
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_missing_refresh_token_returns_400(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/logout/", {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Me (profile)
# ---------------------------------------------------------------------------

class MeTests(APITestCase):

    def setUp(self):
        self.reader = make_reader(email="me@example.com", username="mereader")

    def test_me_unauthenticated_returns_401(self):
        r = self.client.get("/api/v1/accounts/me/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_profile(self):
        self.client.force_authenticate(self.reader)
        r = self.client.get("/api/v1/accounts/me/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["username"], "mereader")
        self.assertEqual(r.data["email"],    "me@example.com")

    def test_me_response_omits_password(self):
        self.client.force_authenticate(self.reader)
        r = self.client.get("/api/v1/accounts/me/")
        self.assertNotIn("password", r.data)

    def test_me_patch_updates_display_name(self):
        self.client.force_authenticate(self.reader)
        r = self.client.patch("/api/v1/accounts/me/", {
            "display_name": "Updated Name",
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.display_name, "Updated Name")

    def test_me_patch_updates_bio(self):
        self.client.force_authenticate(self.reader)
        r = self.client.patch("/api/v1/accounts/me/", {
            "bio": "I love reading news.",
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_me_patch_bio_too_long_returns_400(self):
        self.client.force_authenticate(self.reader)
        r = self.client.patch("/api/v1/accounts/me/", {
            "bio": "x" * 501,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_me_staff_token_rejected(self):
        """Staff JWTs must not work on reader endpoints."""
        staff = make_staff()
        self.client.force_authenticate(staff)
        r = self.client.get("/api/v1/accounts/me/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

class ChangePasswordTests(APITestCase):

    def setUp(self):
        self.reader   = make_reader(email="pw@example.com", username="pwreader")
        self.password = "SecurePass123!"

    def test_change_password_returns_200(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/change-password/", {
            "current_password": self.password,
            "new_password":     "NewSecure456!",
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_change_password_wrong_current_returns_400(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/change-password/", {
            "current_password": "WrongOldPass!",
            "new_password":     "NewSecure456!",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_updates_hash(self):
        self.client.force_authenticate(self.reader)
        self.client.post("/api/v1/accounts/change-password/", {
            "current_password": self.password,
            "new_password":     "NewSecure456!",
        })
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.check_password("NewSecure456!"))
        self.assertFalse(self.reader.check_password(self.password))

    def test_change_password_unauthenticated_returns_401(self):
        r = self.client.post("/api/v1/accounts/change-password/", {
            "current_password": self.password,
            "new_password":     "NewSecure456!",
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_password_weak_new_password_returns_400(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/change-password/", {
            "current_password": self.password,
            "new_password":     "123",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Forgot / reset password
# ---------------------------------------------------------------------------

class ForgotPasswordTests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()
        self.reader = make_reader(email="forgot@example.com", username="forgotreader")

    def test_forgot_known_email_returns_202(self):
        r = self.client.post("/api/v1/accounts/forgot-password/", {
            "email": "forgot@example.com",
        })
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)

    def test_forgot_unknown_email_returns_202(self):
        """Should return 202 regardless to prevent email enumeration."""
        r = self.client.post("/api/v1/accounts/forgot-password/", {
            "email": "nobody@example.com",
        })
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)

    def test_forgot_sets_reset_token(self):
        self.assertIsNone(self.reader.password_reset_token)
        self.client.post("/api/v1/accounts/forgot-password/", {
            "email": "forgot@example.com",
        })
        self.reader.refresh_from_db()
        self.assertIsNotNone(self.reader.password_reset_token)


class ResetPasswordTests(APITestCase):

    def setUp(self):
        self.reader = make_reader(email="reset@example.com", username="resetreader")
        self.reader.password_reset_token         = uuid.uuid4()
        self.reader.password_reset_token_expires = timezone.now() + timedelta(hours=1)
        self.reader.save(
            update_fields=["password_reset_token", "password_reset_token_expires"]
        )

    def test_reset_valid_token_returns_200(self):
        r = self.client.post("/api/v1/accounts/reset-password/", {
            "token":    str(self.reader.password_reset_token),
            "password": "NewResetPass123!",
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_reset_updates_password(self):
        self.client.post("/api/v1/accounts/reset-password/", {
            "token":    str(self.reader.password_reset_token),
            "password": "NewResetPass123!",
        })
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.check_password("NewResetPass123!"))

    def test_reset_clears_token(self):
        self.client.post("/api/v1/accounts/reset-password/", {
            "token":    str(self.reader.password_reset_token),
            "password": "NewResetPass123!",
        })
        self.reader.refresh_from_db()
        self.assertIsNone(self.reader.password_reset_token)

    def test_reset_invalid_token_returns_400(self):
        r = self.client.post("/api/v1/accounts/reset-password/", {
            "token":    str(uuid.uuid4()),
            "password": "NewResetPass123!",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_expired_token_returns_400(self):
        self.reader.password_reset_token_expires = timezone.now() - timedelta(hours=2)
        self.reader.save(update_fields=["password_reset_token_expires"])
        r = self.client.post("/api/v1/accounts/reset-password/", {
            "token":    str(self.reader.password_reset_token),
            "password": "NewResetPass123!",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------

class BookmarkTests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()
        self.reader  = make_reader(email="bm@example.com", username="bmreader")
        self.article = make_article("Bookmark Article")

    def test_list_unauthenticated_returns_401(self):
        r = self.client.get("/api/v1/accounts/bookmarks/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_empty_initially(self):
        self.client.force_authenticate(self.reader)
        r = self.client.get("/api/v1/accounts/bookmarks/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)

    def test_add_bookmark_returns_201(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/bookmarks/", {
            "article_slug": self.article.slug,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_add_bookmark_creates_db_record(self):
        self.client.force_authenticate(self.reader)
        self.client.post("/api/v1/accounts/bookmarks/", {
            "article_slug": self.article.slug,
        })
        self.assertTrue(
            Bookmark.objects.filter(
                reader=self.reader, article=self.article
            ).exists()
        )

    def test_add_duplicate_bookmark_returns_409(self):
        self.client.force_authenticate(self.reader)
        self.client.post("/api/v1/accounts/bookmarks/", {
            "article_slug": self.article.slug,
        })
        r = self.client.post("/api/v1/accounts/bookmarks/", {
            "article_slug": self.article.slug,
        })
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

    def test_add_bookmark_unauthenticated_returns_401(self):
        r = self.client.post("/api/v1/accounts/bookmarks/", {
            "article_slug": self.article.slug,
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_add_bookmark_unknown_slug_returns_400(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/bookmarks/", {
            "article_slug": "does-not-exist",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_shows_added_bookmark(self):
        Bookmark.objects.create(reader=self.reader, article=self.article)
        self.client.force_authenticate(self.reader)
        r = self.client.get("/api/v1/accounts/bookmarks/")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["article"]["slug"], self.article.slug)

    def test_remove_bookmark_returns_200(self):
        Bookmark.objects.create(reader=self.reader, article=self.article)
        self.client.force_authenticate(self.reader)
        r = self.client.delete(
            f"/api/v1/accounts/bookmarks/{self.article.slug}/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_remove_bookmark_deletes_db_record(self):
        Bookmark.objects.create(reader=self.reader, article=self.article)
        self.client.force_authenticate(self.reader)
        self.client.delete(f"/api/v1/accounts/bookmarks/{self.article.slug}/")
        self.assertFalse(
            Bookmark.objects.filter(
                reader=self.reader, article=self.article
            ).exists()
        )

    def test_remove_nonexistent_bookmark_returns_200(self):
        """Delete is idempotent."""
        self.client.force_authenticate(self.reader)
        r = self.client.delete(
            f"/api/v1/accounts/bookmarks/{self.article.slug}/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_remove_bookmark_unauthenticated_returns_401(self):
        r = self.client.delete(
            f"/api/v1/accounts/bookmarks/{self.article.slug}/"
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_bookmark_count_cached_in_profile(self):
        Bookmark.objects.create(reader=self.reader, article=self.article)
        self.client.force_authenticate(self.reader)
        r = self.client.get("/api/v1/accounts/me/")
        self.assertEqual(r.data["bookmark_count"], 1)


# ---------------------------------------------------------------------------
# Reading history
# ---------------------------------------------------------------------------

class ReadingHistoryTests(APITestCase):

    def setUp(self):
        self.reader  = make_reader(email="hist@example.com", username="histreader")
        self.article = make_article("History Article")

    def test_list_unauthenticated_returns_401(self):
        r = self.client.get("/api/v1/accounts/history/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_empty_initially(self):
        self.client.force_authenticate(self.reader)
        r = self.client.get("/api/v1/accounts/history/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)

    def test_record_read_returns_201_on_first_visit(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/history/", {
            "article_slug": self.article.slug,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_record_read_creates_db_record(self):
        self.client.force_authenticate(self.reader)
        self.client.post("/api/v1/accounts/history/", {
            "article_slug": self.article.slug,
        })
        self.assertTrue(
            ReadingHistory.objects.filter(
                reader=self.reader, article=self.article
            ).exists()
        )

    def test_record_read_increments_read_count(self):
        self.client.force_authenticate(self.reader)
        self.client.post("/api/v1/accounts/history/", {
            "article_slug": self.article.slug,
        })
        self.client.post("/api/v1/accounts/history/", {
            "article_slug": self.article.slug,
        })
        entry = ReadingHistory.objects.get(reader=self.reader, article=self.article)
        self.assertEqual(entry.read_count, 2)

    def test_record_read_returns_200_on_revisit(self):
        self.client.force_authenticate(self.reader)
        self.client.post("/api/v1/accounts/history/", {
            "article_slug": self.article.slug,
        })
        r = self.client.post("/api/v1/accounts/history/", {
            "article_slug": self.article.slug,
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_list_shows_recorded_articles(self):
        ReadingHistory.objects.create(reader=self.reader, article=self.article)
        self.client.force_authenticate(self.reader)
        r = self.client.get("/api/v1/accounts/history/")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["article"]["slug"], self.article.slug)

    def test_clear_history_returns_200(self):
        ReadingHistory.objects.create(reader=self.reader, article=self.article)
        self.client.force_authenticate(self.reader)
        r = self.client.delete("/api/v1/accounts/history/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_clear_history_removes_all_entries(self):
        ReadingHistory.objects.create(reader=self.reader, article=self.article)
        self.client.force_authenticate(self.reader)
        self.client.delete("/api/v1/accounts/history/")
        self.assertEqual(
            ReadingHistory.objects.filter(reader=self.reader).count(), 0
        )

    def test_clear_history_unauthenticated_returns_401(self):
        r = self.client.delete("/api/v1/accounts/history/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_record_unknown_article_returns_400(self):
        self.client.force_authenticate(self.reader)
        r = self.client.post("/api/v1/accounts/history/", {
            "article_slug": "does-not-exist",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Model unit tests
# ---------------------------------------------------------------------------

class ReaderAccountModelTests(TestCase):

    def test_set_password_hashes_value(self):
        reader = ReaderAccount(email="hash@example.com", username="hashtest")
        reader.set_password("PlainText123!")
        self.assertNotEqual(reader.password, "PlainText123!")

    def test_check_password_correct(self):
        reader = ReaderAccount(email="check@example.com", username="checktest")
        reader.set_password("CorrectPass123!")
        self.assertTrue(reader.check_password("CorrectPass123!"))

    def test_check_password_wrong(self):
        reader = ReaderAccount(email="wrong@example.com", username="wrongtest")
        reader.set_password("CorrectPass123!")
        self.assertFalse(reader.check_password("WrongPass!"))

    def test_is_authenticated_true(self):
        reader = ReaderAccount()
        self.assertTrue(reader.is_authenticated)

    def test_is_anonymous_false(self):
        reader = ReaderAccount()
        self.assertFalse(reader.is_anonymous)

    def test_public_name_falls_back_to_username(self):
        reader = ReaderAccount(username="fallback", display_name="")
        self.assertEqual(reader.public_name, "fallback")

    def test_public_name_prefers_display_name(self):
        reader = ReaderAccount(username="user", display_name="Display")
        self.assertEqual(reader.public_name, "Display")
