import logging
import time

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("core.views")


class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = []

    def get(self, request) -> Response:
        start   = time.monotonic()
        checks  = {}
        healthy = True

        # Database check
        try:
            conn = connections["default"]
            conn.ensure_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except OperationalError as exc:
            checks["database"] = f"error: {exc}"
            healthy = False
            logger.error("Health check: database unreachable — %s", exc)

        # Redis check
        try:
            from django.core.cache import cache
            cache.set("health:probe", "1", timeout=5)
            if cache.get("health:probe") != "1":
                raise RuntimeError("Cache read returned unexpected value.")
            checks["cache"] = "ok"
        except Exception as exc:
            checks["cache"] = f"error: {exc}"
            healthy = False
            logger.error("Health check: cache unreachable — %s", exc)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return Response(
            {
                "status":           "healthy" if healthy else "degraded",
                "checks":           checks,
                "version":          settings.SPECTACULAR_SETTINGS.get("VERSION", "unknown"),
                "response_time_ms": elapsed_ms,
            },
            status=200 if healthy else 503,
        )


class APIRootView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = []

    def get(self, request) -> Response:
        base = request.build_absolute_uri("/api/v1/")
        return Response({
            "status":  "ok",
            "version": "v1",
            "endpoints": {
                "articles":    f"{base}articles/",
                "breaking":    f"{base}articles/breaking/",
                "top_stories": f"{base}articles/top-stories/",
                "featured":    f"{base}articles/featured/",
                "categories":  f"{base}categories/",
                "tags":        f"{base}tags/",
                "authors":     f"{base}authors/",
                "staff":       f"{base}staff/",
                "me":          f"{base}auth/me/",
                "schema":      request.build_absolute_uri("/api/schema/"),
                "docs":        request.build_absolute_uri("/api/docs/"),
                "health":      request.build_absolute_uri("/health/"),
            },
        })
