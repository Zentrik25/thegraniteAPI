"""
urls.py — URL routing for the reader accounts app.

All routes are mounted under /api/v1/ in the project urls.py:
    path("api/v1/", include("accounts.urls"))

Which resolves to:
  POST   /api/v1/accounts/register/
  GET    /api/v1/accounts/verify-email/?token=
  POST   /api/v1/accounts/login/
  POST   /api/v1/accounts/logout/
  POST   /api/v1/accounts/token/refresh/
  GET    /api/v1/accounts/me/
  PATCH  /api/v1/accounts/me/
  POST   /api/v1/accounts/change-password/
  POST   /api/v1/accounts/forgot-password/
  POST   /api/v1/accounts/reset-password/
  GET    /api/v1/accounts/bookmarks/
  POST   /api/v1/accounts/bookmarks/
  DELETE /api/v1/accounts/bookmarks/<slug>/
  GET    /api/v1/accounts/history/
  POST   /api/v1/accounts/history/
  DELETE /api/v1/accounts/history/
"""

from django.urls import path

from .views import (
    BookmarkDeleteView,
    BookmarkListCreateView,
    ChangePasswordView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    ReadingHistoryView,
    ReaderTokenRefreshView,
    RegisterView,
    ResendVerificationView,
    ResetPasswordView,
    VerifyEmailView,
)

app_name = "accounts"

urlpatterns = [
    # -- Registration & email verification ---------------------------------
    path("accounts/register/",             RegisterView.as_view(),           name="register"),
    path("accounts/verify-email/",         VerifyEmailView.as_view(),        name="verify-email"),
    path("accounts/resend-verification/",  ResendVerificationView.as_view(), name="resend-verification"),

    # -- Authentication ----------------------------------------------------
    path("accounts/login/",          LoginView.as_view(),              name="login"),
    path("accounts/logout/",         LogoutView.as_view(),             name="logout"),
    path("accounts/token/refresh/",  ReaderTokenRefreshView.as_view(), name="token-refresh"),

    # -- Profile -----------------------------------------------------------
    path("accounts/me/",               MeView.as_view(),             name="me"),
    path("accounts/change-password/",  ChangePasswordView.as_view(), name="change-password"),

    # -- Password reset ----------------------------------------------------
    path("accounts/forgot-password/",  ForgotPasswordView.as_view(), name="forgot-password"),
    path("accounts/reset-password/",   ResetPasswordView.as_view(),  name="reset-password"),

    # -- Bookmarks ---------------------------------------------------------
    path("accounts/bookmarks/",              BookmarkListCreateView.as_view(), name="bookmark-list"),
    path("accounts/bookmarks/<slug:slug>/",  BookmarkDeleteView.as_view(),     name="bookmark-delete"),

    # -- Reading history ---------------------------------------------------
    path("accounts/history/", ReadingHistoryView.as_view(), name="history"),
]
