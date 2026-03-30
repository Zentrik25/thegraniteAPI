import json
from unittest.mock import MagicMock, patch

from config import settings as project_settings_module
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.exceptions import NotFound, Throttled, ValidationError
from rest_framework.test import APIRequestFactory, APITestCase

from core.cache import get_or_set_cache, invalidate_keys, make_cache_key
from core.exceptions import _flatten_errors, structured_exception_handler
from core.middleware import RequestTimingMiddleware, StructuredLoggingMiddleware
from core.throttling import BurstRateThrottle, RoleBasedThrottle

User = get_user_model()


def make_user(username, role="contributor", **kwargs):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class MakeCacheKeyTests(TestCase):

    def test_key_is_namespaced(self):
        self.assertTrue(make_cache_key("articles:top_stories").startswith("gp:"))

    def test_long_key_is_hashed(self):
        result = make_cache_key("a" * 300)
        self.assertLessEqual(len(result), 200)
        self.assertIn(":h:", result)

    def test_short_key_preserves_content(self):
        result = make_cache_key("articles:detail:my-slug")
        self.assertIn("articles:detail:my-slug", result)


class GetOrSetCacheTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_returns_computed_value_on_miss(self):
        self.assertEqual(get_or_set_cache("test:k1", lambda: 42, ttl=10), 42)

    def test_returns_cached_value_on_hit(self):
        get_or_set_cache("test:k2", lambda: "first", ttl=60)
        self.assertEqual(get_or_set_cache("test:k2", lambda: "second", ttl=60), "first")

    def test_compute_called_only_once(self):
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return "value"

        get_or_set_cache("test:k3", compute, ttl=60)
        get_or_set_cache("test:k3", compute, ttl=60)
        self.assertEqual(calls["n"], 1)


class InvalidateKeysTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_invalidate_removes_key(self):
        get_or_set_cache("test:inv1", lambda: "data", ttl=60)
        invalidate_keys("test:inv1")
        self.assertIsNone(cache.get(make_cache_key("test:inv1")))


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RequestTimingMiddlewareTests(TestCase):

    def test_x_response_time_header_present(self):
        response = self.client.get("/health/")
        self.assertIn("X-Response-Time", response)

    def test_x_response_time_ends_in_ms(self):
        response = self.client.get("/health/")
        self.assertTrue(response["X-Response-Time"].endswith("ms"))

    def test_slow_request_logs_redact_sensitive_query_params(self):
        factory = APIRequestFactory()
        request = factory.get("/api/v1/accounts/verify-email/?token=super-secret&foo=bar")
        middleware = RequestTimingMiddleware(lambda req: HttpResponse("ok"))

        with patch("core.middleware.time.monotonic", side_effect=[0.0, 6.0]):
            with self.assertLogs("core.middleware", level="CRITICAL") as captured:
                middleware(request)

        output = "\n".join(captured.output)
        self.assertNotIn("super-secret", output)
        self.assertIn("foo=bar", output)


class StructuredLoggingMiddlewareTests(TestCase):

    def test_x_request_id_header_present(self):
        response = self.client.get("/health/")
        self.assertIn("X-Request-ID", response)

    def test_x_request_id_is_valid_uuid(self):
        import uuid
        response = self.client.get("/health/")
        uuid.UUID(response["X-Request-ID"])  # raises if invalid

    def test_query_extra_redacts_sensitive_tokens(self):
        factory = APIRequestFactory()
        request = factory.get("/api/v1/newsletter/confirm/?token=live-token&source=postman")
        middleware = StructuredLoggingMiddleware(lambda req: HttpResponse("ok"))

        with patch("core.middleware.logger.info") as mock_info:
            middleware(request)

        logged_query = mock_info.call_args.kwargs["extra"]["query"]
        self.assertNotIn("live-token", logged_query)
        self.assertIn("source=postman", logged_query)


class SecurityConfigurationTests(TestCase):

    def test_production_rejects_placeholder_secret_key(self):
        with self.assertRaises(ImproperlyConfigured):
            project_settings_module._validate_security_settings(
                debug=False,
                testing=False,
                secret_key=project_settings_module._INSECURE_SECRET_KEY,
            )

    def test_debug_runtime_allows_placeholder_secret_key(self):
        project_settings_module._validate_security_settings(
            debug=True,
            testing=False,
            secret_key=project_settings_module._INSECURE_SECRET_KEY,
        )

    def test_test_runtime_uses_relaxed_secure_defaults(self):
        self.assertFalse(project_settings_module._PRODUCTION)
        self.assertFalse(project_settings_module.SECURE_SSL_REDIRECT)
        self.assertFalse(project_settings_module.SESSION_COOKIE_SECURE)
        self.assertFalse(project_settings_module.CSRF_COOKIE_SECURE)
        self.assertEqual(project_settings_module.SECURE_HSTS_SECONDS, 0)


class EmailConfigurationTests(TestCase):
    """
    Guard that _validate_email_settings fails fast in production when
    EMAIL_HOST is still pointing at localhost, and is relaxed in non-production.
    """

    _smtp = "django.core.mail.backends.smtp.EmailBackend"

    def test_production_smtp_with_localhost_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            project_settings_module._validate_email_settings(
                production=True,
                email_host="localhost",
                email_backend=self._smtp,
            )

    def test_production_smtp_with_127_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            project_settings_module._validate_email_settings(
                production=True,
                email_host="127.0.0.1",
                email_backend=self._smtp,
            )

    def test_production_smtp_with_real_host_passes(self):
        # Should not raise for a real SMTP relay.
        project_settings_module._validate_email_settings(
            production=True,
            email_host="smtp.sendgrid.net",
            email_backend=self._smtp,
        )

    def test_production_console_backend_is_not_checked(self):
        # Console backend is never SMTP — validation does not apply.
        project_settings_module._validate_email_settings(
            production=True,
            email_host="localhost",
            email_backend="django.core.mail.backends.console.EmailBackend",
        )

    def test_debug_runtime_skips_email_check(self):
        # No error even with SMTP + localhost in non-production mode.
        project_settings_module._validate_email_settings(
            production=False,
            email_host="localhost",
            email_backend=self._smtp,
        )

    def test_current_test_run_passes_email_check(self):
        # The test run uses locmem backend — validation must never block tests.
        self.assertFalse(project_settings_module._PRODUCTION)


class CeleryEagerModeTests(TestCase):
    """
    Guard that CELERY_TASK_ALWAYS_EAGER is on in tests but off by default
    for non-test environments.

    These tests cannot cover the production runtime directly (that would
    require a separate settings module), but they verify the two observable
    conditions that the guard relies on:
      1. _TESTING is True when Django's test runner is active.
      2. The setting is therefore True in the current (test) run.
    """

    def test_eager_mode_enabled_during_test_run(self):
        """CELERY_TASK_ALWAYS_EAGER must be True when the test runner is active."""
        from django.conf import settings as django_settings
        self.assertTrue(
            django_settings.CELERY_TASK_ALWAYS_EAGER,
            "CELERY_TASK_ALWAYS_EAGER should be True during tests so tasks run "
            "synchronously without a broker.",
        )

    def test_testing_flag_is_true_in_test_runner(self):
        """_TESTING is True when 'test' is in sys.argv — i.e. right now."""
        self.assertTrue(
            project_settings_module._TESTING,
            "_TESTING must be True during test runs so the eager-mode gate works.",
        )

    def test_env_flag_false_by_default(self):
        """_env_flag returns False when the env var is absent — safe default for prod."""
        import os
        env_var = "CELERY_TASK_ALWAYS_EAGER"
        original = os.environ.pop(env_var, None)
        try:
            self.assertFalse(
                project_settings_module._env_flag(env_var, default=False),
                "_env_flag must default to False so production stays async unless "
                "explicitly opted in.",
            )
        finally:
            if original is not None:
                os.environ[env_var] = original


class MaintenanceModeTests(TestCase):

    def test_normal_requests_pass_through(self):
        response = self.client.get("/health/")
        self.assertNotEqual(response.status_code, 503)

    @override_settings(MAINTENANCE_MODE=True)
    def test_maintenance_returns_503_for_api(self):
        response = self.client.get("/api/v1/articles/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["code"], "maintenance")

    @override_settings(MAINTENANCE_MODE=True)
    def test_health_check_bypasses_maintenance(self):
        self.assertNotEqual(self.client.get("/health/").status_code, 503)


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------

class RoleBasedThrottleTests(TestCase):

    def _request(self, user=None):
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = user or MagicMock(is_authenticated=False)
        return request

    def test_anon_scope(self):
        self.assertEqual(RoleBasedThrottle().get_scope(self._request()), "anon")

    def test_author_scope(self):
        u = make_user("t_author", role="author")
        self.assertEqual(RoleBasedThrottle().get_scope(self._request(u)), "author")

    def test_admin_scope(self):
        u = make_user("t_admin", role="admin")
        self.assertEqual(RoleBasedThrottle().get_scope(self._request(u)), "admin")


class BurstRateThrottleTests(TestCase):

    def test_get_always_allowed(self):
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = MagicMock(is_authenticated=False)
        self.assertTrue(BurstRateThrottle().allow_request(request, None))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ExceptionHandlerTests(TestCase):

    def _ctx(self):
        req            = MagicMock()
        req.request_id = "test-uuid"
        req.path       = "/api/v1/test/"
        return {"request": req, "view": MagicMock()}

    def test_not_found_code(self):
        r = structured_exception_handler(NotFound(), self._ctx())
        self.assertEqual(r.data["code"], "not_found")
        self.assertEqual(r.data["status"], "error")

    def test_throttled_includes_retry_after(self):
        r = structured_exception_handler(Throttled(wait=30), self._ctx())
        self.assertEqual(r.data["code"], "rate_limit_exceeded")
        self.assertEqual(r.data["retry_after_seconds"], 30)

    def test_validation_error_includes_errors_field(self):
        r = structured_exception_handler(
            ValidationError({"title": ["This field is required."]}),
            self._ctx(),
        )
        self.assertEqual(r.data["code"], "validation_error")
        self.assertIn("errors", r.data)
        self.assertIn("title", r.data["errors"])

    def test_request_id_in_response(self):
        r = structured_exception_handler(NotFound(), self._ctx())
        self.assertEqual(r.data["request_id"], "test-uuid")


class FlattenErrorsTests(TestCase):

    def test_simple_field(self):
        self.assertEqual(
            _flatten_errors({"title": ["Required."]}),
            {"title": "Required."},
        )

    def test_nested_field(self):
        result = _flatten_errors({"author": {"email": ["Invalid."]}})
        self.assertIn("author.email", result)

    def test_multiple_errors_returns_first(self):
        result = _flatten_errors({"slug": ["Too long.", "Invalid characters."]})
        self.assertEqual(result["slug"], "Too long.")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginationTests(APITestCase):

    def test_response_has_required_fields(self):
        r = self.client.get("/api/v1/articles/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ("status", "count", "total_pages", "current_page", "results"):
            self.assertIn(field, r.data)

    def test_status_field_is_ok(self):
        self.assertEqual(self.client.get("/api/v1/articles/").data["status"], "ok")

    def test_page_size_override(self):
        r = self.client.get("/api/v1/articles/?page_size=5")
        self.assertLessEqual(len(r.data["results"]), 5)

    def test_page_size_capped(self):
        r = self.client.get("/api/v1/articles/?page_size=9999")
        self.assertLessEqual(len(r.data["results"]), 100)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class HealthCheckTests(APITestCase):

    def test_healthy_returns_200(self):
        r = self.client.get("/health/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "healthy")

    def test_response_structure(self):
        r = self.client.get("/health/")
        self.assertIn("checks",           r.data)
        self.assertIn("database",         r.data["checks"])
        self.assertIn("cache",            r.data["checks"])
        self.assertIn("celery_broker",    r.data["checks"])
        self.assertIn("response_time_ms", r.data)

    def test_checks_ok_in_test_env(self):
        r = self.client.get("/health/")
        self.assertEqual(r.data["checks"]["database"], "ok")
        self.assertEqual(r.data["checks"]["cache"],    "ok")

    def test_celery_broker_key_present_in_checks(self):
        """celery_broker is always present — informational, never degrades status."""
        r = self.client.get("/health/")
        self.assertIn("celery_broker", r.data["checks"])

    def test_celery_broker_reports_memory_in_test_env(self):
        """In tests the broker is memory://, key should say so."""
        r = self.client.get("/health/")
        self.assertEqual(r.data["checks"]["celery_broker"], "memory (no worker)")

    @override_settings(CELERY_BROKER_URL="redis://localhost:6379/0")
    def test_celery_broker_reports_redis_when_configured(self):
        """If broker URL starts with redis, key reports 'redis'."""
        r = self.client.get("/health/")
        self.assertEqual(r.data["checks"]["celery_broker"], "redis")

    def test_celery_broker_field_does_not_affect_status(self):
        """memory:// broker must not degrade the healthy status — it is informational."""
        r = self.client.get("/health/")
        # Even with memory:// broker the overall status must be healthy in test env
        self.assertEqual(r.data["status"], "healthy")

    @patch("django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection")
    def test_db_failure_returns_503(self, mock_conn):
        from django.db.utils import OperationalError
        mock_conn.side_effect = OperationalError("connection refused")
        r = self.client.get("/health/")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data["status"], "degraded")


# ---------------------------------------------------------------------------
# JWT login
# ---------------------------------------------------------------------------

class JWTLoginTests(APITestCase):

    def setUp(self):
        self.editor = make_user("jwt_editor", role="editor")
        self.editor.set_password("Str0ng!Pass99")
        self.editor.save()

    def test_login_returns_tokens(self):
        r = self.client.post("/api/auth/login/", {
            "username": "jwt_editor",
            "password": "Str0ng!Pass99",
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("access",  r.data)
        self.assertIn("refresh", r.data)

    def test_login_response_includes_user_object(self):
        r = self.client.post("/api/auth/login/", {
            "username": "jwt_editor",
            "password": "Str0ng!Pass99",
        })
        self.assertIn("user", r.data)
        u = r.data["user"]
        self.assertEqual(u["role"], "editor")
        self.assertTrue(u["can_publish"])
        self.assertIn("can_edit_any_article", u)
        self.assertIn("can_manage_staff",     u)

    def test_wrong_password_returns_401(self):
        r = self.client.post("/api/auth/login/", {
            "username": "jwt_editor",
            "password": "wrongpassword",
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(r.data["code"], "authentication_failed")


# ---------------------------------------------------------------------------
# Celery broker validation
# ---------------------------------------------------------------------------

class CeleryBrokerValidationTests(TestCase):
    """
    Guard that _validate_celery_settings fails fast in production when the
    broker falls back to the in-process memory transport, and is relaxed
    (non-raising) in non-production contexts.
    """

    def test_production_memory_broker_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            project_settings_module._validate_celery_settings(
                production=True,
                broker_url="memory://",
            )

    def test_production_redis_broker_passes(self):
        # Should not raise for a real Redis DSN.
        project_settings_module._validate_celery_settings(
            production=True,
            broker_url="redis://redis.example.com:6379/0",
        )

    def test_production_rediss_broker_passes(self):
        # TLS Redis URLs (rediss://) must also pass.
        project_settings_module._validate_celery_settings(
            production=True,
            broker_url="rediss://redis.example.com:6380/0",
        )

    def test_non_production_memory_broker_passes(self):
        # Dev/test with memory:// is allowed — validation is production-only.
        project_settings_module._validate_celery_settings(
            production=False,
            broker_url="memory://",
        )

    def test_current_test_run_passes_celery_check(self):
        # _PRODUCTION is False during tests so the validator never fires,
        # and the test broker (memory://) is valid.
        self.assertFalse(project_settings_module._PRODUCTION)

    def test_error_message_mentions_redis_url(self):
        """Operator guidance must name the env var that fixes the problem."""
        try:
            project_settings_module._validate_celery_settings(
                production=True,
                broker_url="memory://",
            )
        except ImproperlyConfigured as exc:
            self.assertIn("REDIS_URL", str(exc))
        else:
            self.fail("Expected ImproperlyConfigured was not raised.")


class CeleryStartupWarningTests(TestCase):
    """
    Guard that _warn_if_memory_broker logs at WARNING level when the broker
    is memory:// and eager mode is off, and stays silent otherwise.
    """

    def _get_config(self):
        import importlib
        from core.apps import CoreConfig
        return CoreConfig("core", importlib.import_module("core"))

    def test_memory_broker_without_eager_logs_warning(self):
        cfg = self._get_config()
        with override_settings(CELERY_TASK_ALWAYS_EAGER=False, CELERY_BROKER_URL="memory://"):
            with self.assertLogs("core", level="WARNING") as captured:
                cfg._warn_if_memory_broker()
        combined = "\n".join(captured.output)
        self.assertIn("memory://", combined)

    def test_eager_mode_suppresses_warning(self):
        """With eager mode on tasks are synchronous — no warning needed."""
        cfg = self._get_config()
        with override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_BROKER_URL="memory://"):
            # assertLogs would fail if no message is emitted at WARNING+;
            # use assertNoLogs (Django 4.1+) or a manual check.
            import logging
            with self.assertRaises(AssertionError):
                with self.assertLogs("core", level="WARNING"):
                    cfg._warn_if_memory_broker()

    def test_redis_broker_suppresses_warning(self):
        """Real Redis broker → no warning regardless of eager flag."""
        cfg = self._get_config()
        with override_settings(
            CELERY_TASK_ALWAYS_EAGER=False,
            CELERY_BROKER_URL="redis://localhost:6379/0",
        ):
            with self.assertRaises(AssertionError):
                with self.assertLogs("core", level="WARNING"):
                    cfg._warn_if_memory_broker()

    def test_current_test_run_does_not_warn(self):
        """In the actual test suite eager mode is on — warning must be silent."""
        from django.conf import settings as s
        self.assertTrue(s.CELERY_TASK_ALWAYS_EAGER)
