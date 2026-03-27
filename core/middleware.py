import logging
import time
import uuid

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("core.middleware")


class RequestTimingMiddleware:
    WARN_MS     = 500
    ERROR_MS    = 2_000
    CRITICAL_MS = 5_000

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start    = time.monotonic()
        response = self.get_response(request)
        ms       = int((time.monotonic() - start) * 1_000)

        response["X-Response-Time"] = f"{ms}ms"

        path = request.get_full_path()
        if ms >= self.CRITICAL_MS:
            logger.critical("CRITICAL slow request: %s %s — %dms", request.method, path, ms)
        elif ms >= self.ERROR_MS:
            logger.error("SLA breach: %s %s — %dms", request.method, path, ms)
        elif ms >= self.WARN_MS:
            logger.warning("Slow request: %s %s — %dms", request.method, path, ms)

        return response


class StructuredLoggingMiddleware:
    SILENT_PATHS = frozenset(["/health/", "/favicon.ico"])

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id         = str(uuid.uuid4())
        request.request_id = request_id

        start    = time.monotonic()
        response = self.get_response(request)
        ms       = int((time.monotonic() - start) * 1_000)

        response["X-Request-ID"] = request_id

        if request.path not in self.SILENT_PATHS:
            user_id = (
                request.user.pk
                if hasattr(request, "user") and request.user.is_authenticated
                else None
            )
            logger.info(
                "%s %s %d",
                request.method,
                request.path,
                response.status_code,
                extra={
                    "request_id":  request_id,
                    "method":      request.method,
                    "path":        request.path,
                    "query":       request.META.get("QUERY_STRING", ""),
                    "status_code": response.status_code,
                    "user_id":     user_id,
                    "ip":          _get_client_ip(request),
                    "user_agent":  request.META.get("HTTP_USER_AGENT", "")[:200],
                    "elapsed_ms":  ms,
                },
            )

        return response


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Frame-Options",        "DENY")
        response.setdefault("Referrer-Policy",         "strict-origin-when-cross-origin")
        response.setdefault(
            "Permissions-Policy",
            "accelerometer=(), camera=(), geolocation=(), "
            "gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",
        )
        return response


class MaintenanceModeMiddleware:
    ALWAYS_ALLOWED = frozenset(["/health/", "/admin/"])

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_maintenance():
            if not any(request.path.startswith(p) for p in self.ALWAYS_ALLOWED):
                return JsonResponse(
                    {
                        "status":  "error",
                        "code":    "maintenance",
                        "message": "The Granite Post API is temporarily offline for maintenance. "
                                   "We will be back shortly.",
                    },
                    status=503,
                )
        return self.get_response(request)

    @staticmethod
    def _is_maintenance() -> bool:
        if getattr(settings, "MAINTENANCE_MODE", False):
            return True
        try:
            from django.core.cache import cache
            return bool(cache.get("maintenance_mode"))
        except Exception:
            return False


def _get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
