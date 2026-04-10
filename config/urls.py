"""
urls.py — Root URL configuration for The Granite Post.

Route map
---------
/admin/                  — Django admin
/health/                 — Health check (DB + cache)
/api/v1/                 — API root (endpoint index)
/api/v1/articles/…       — Articles, categories, tags
/api/v1/users/…          — Public author profiles
/api/v1/staff/…          — Staff management (Senior Editor / Admin)
/api/v1/auth/token/      — Obtain JWT pair
/api/v1/auth/token/refresh/ — Refresh access token
/api/v1/auth/token/blacklist/ — Logout (blacklist refresh token)
/api/v1/auth/me/         — Current user profile
/api/v1/auth/change-password/ — Change own password
/api/schema/             — OpenAPI 3 schema (YAML/JSON)
/api/docs/               — Swagger UI
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView, TokenBlacklistView

from core.jwt import GraniteTokenObtainPairView

urlpatterns = [
    # ── Django admin ──────────────────────────────────────────────────
    path("admin/", admin.site.urls),

    # ── Health + API root ─────────────────────────────────────────────
    path("", include("core.urls")),

    # ── RSS feeds + sitemaps ──────────────────────────────────────────
    path("", include("feeds.urls")),

    # ── API v1 ────────────────────────────────────────────────────────
    path("api/v1/", include("articles.urls")),
    path("api/v1/", include("users.urls")),
    path("api/v1/", include("analytics.urls")),
    path("api/v1/", include("comments.urls")),
    path("api/v1/", include("newsletter.urls")),
    path("api/v1/", include("media_assets.urls")),
    path("api/v1/", include("search.urls")),
    path("api/v1/", include("sections.urls")),
    path("api/v1/", include("redirects.urls")),
    path("api/v1/", include("audit.urls")),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/", include("advertising.urls")),
    path("api/v1/", include("notifications.urls")),
    path("api/v1/", include("subscriptions.urls")),

    # ── Auth (JWT) ────────────────────────────────────────────────────
    path("api/v1/auth/token/",           GraniteTokenObtainPairView.as_view(), name="token-obtain"),
    path("api/v1/auth/token/refresh/",   TokenRefreshView.as_view(),           name="token-refresh"),
    path("api/v1/auth/token/blacklist/", TokenBlacklistView.as_view(),         name="token-blacklist"),

    # ── OpenAPI schema + docs ─────────────────────────────────────────
    path("api/schema/", SpectacularAPIView.as_view(),      name="schema"),
    path("api/docs/",   SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
