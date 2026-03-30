import os
import sys
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

_TESTING = "test" in sys.argv
_INSECURE_SECRET_KEY = "django-insecure-change-me-in-production"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_production_runtime(debug: bool, testing: bool) -> bool:
    """Return True only for non-debug, non-test runtime."""
    return not debug and not testing


def _validate_security_settings(*, debug: bool, testing: bool, secret_key: str) -> None:
    """Fail fast when production would boot with an unsafe secret key."""
    if _is_production_runtime(debug, testing) and (
        not secret_key or secret_key == _INSECURE_SECRET_KEY
    ):
        raise ImproperlyConfigured(
            "SECRET_KEY must be set to a non-default value when DEBUG=False."
        )


def _validate_celery_settings(
    *,
    production: bool,
    broker_url: str,
) -> None:
    """
    Fail fast in production when the Celery broker has fallen back to the
    in-process memory transport.

    The memory:// broker is ephemeral and process-local: tasks enqueued by the
    web worker are never consumed by a Celery worker and are silently lost on
    process restart.  Affected tasks include payment callbacks, subscription
    expiry checks, and transactional email delivery.

    Production MUST supply REDIS_URL so the broker resolves to redis://.
    """
    if not production:
        return
    if broker_url.startswith("memory://"):
        raise ImproperlyConfigured(
            "CELERY_BROKER_URL resolves to memory:// in production. "
            "Set the REDIS_URL environment variable to a real Redis DSN. "
            "Without it, tasks (payment callbacks, expiry checks, email "
            "delivery) will be silently dropped."
        )


def _validate_email_settings(
    *,
    production: bool,
    email_host: str,
    email_backend: str,
) -> None:
    """
    Fail fast when production is configured to send real SMTP email but
    EMAIL_HOST is still pointing at localhost — that means the operator
    forgot to set a real relay and every transactional email will silently
    fail to deliver.
    """
    if not production:
        return
    smtp_backend = "django.core.mail.backends.smtp.EmailBackend"
    if email_backend == smtp_backend and email_host in ("localhost", "127.0.0.1", ""):
        raise ImproperlyConfigured(
            "EMAIL_HOST must be set to a real SMTP relay when DEBUG=False. "
            "Currently pointing at localhost, which will not deliver email in production."
        )

# Load .env file before anything else
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _value = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _value.strip())

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    _INSECURE_SECRET_KEY,
)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

DEBUG = _env_flag("DEBUG", default=False)
_PRODUCTION = _is_production_runtime(DEBUG, _TESTING)
_validate_security_settings(debug=DEBUG, testing=_TESTING, secret_key=SECRET_KEY)

MAINTENANCE_MODE = _env_flag("MAINTENANCE_MODE", default=False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.postgres",

    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",

    # Project apps — order matters
    "users.apps.UsersConfig",
    "articles.apps.ArticlesConfig",
    "core.apps.CoreConfig",
    "analytics.apps.AnalyticsConfig",
    "comments.apps.CommentsConfig",
    "newsletter.apps.NewsletterConfig",
    "feeds.apps.FeedsConfig",
    "media_assets.apps.MediaAssetsConfig",
    "search.apps.SearchConfig",
    "sections.apps.SectionsConfig",
    "redirects.apps.RedirectsConfig",
    "audit.apps.AuditConfig",
    "accounts.apps.AccountsConfig",
    "advertising.apps.AdvertisingConfig",
    "notifications.apps.NotificationsConfig",
    "subscriptions.apps.SubscriptionsConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "redirects.middleware.RedirectMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.StructuredLoggingMiddleware",
    "core.middleware.RequestTimingMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
    "core.middleware.MaintenanceModeMiddleware",
    "subscriptions.middleware.PaywallMiddleware",
]

ROOT_URLCONF     = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
AUTH_USER_MODEL  = "users.StaffUser"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Database
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if _DATABASE_URL:
    import dj_database_url
    DATABASES = {"default": dj_database_url.parse(_DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME":   BASE_DIR / "db.sqlite3",
        }
    }

# Cache
REDIS_URL = os.environ.get("REDIS_URL", "")
# Redis stays the production default, but local DEBUG mode can run without it.
USE_REDIS = bool(REDIS_URL) and not _TESTING and (not DEBUG or _env_flag("USE_REDIS", default=False))

if USE_REDIS:
    CACHES = {
        "default": {
            "BACKEND":    "django.core.cache.backends.redis.RedisCache",
            "LOCATION":   REDIS_URL,
            "KEY_PREFIX": "granite",
            "OPTIONS":    {"socket_connect_timeout": 5},
        },
        "throttle": {
            "BACKEND":    "django.core.cache.backends.redis.RedisCache",
            "LOCATION":   REDIS_URL,
            "KEY_PREFIX": "granite:throttle",
            "OPTIONS":    {"socket_connect_timeout": 5},
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND":  "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "granite-default",
        },
        "throttle": {
            "BACKEND":  "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "granite-throttle",
        },
    }

CACHE_KEYS = {
    "ARTICLE_DETAIL":  "articles:detail:{slug}",
    "ARTICLE_LIST":    "articles:list",
    "TOP_STORIES":     "articles:top_stories",
    "BREAKING_NEWS":   "articles:breaking",
    "FEATURED":        "articles:featured",
    "CATEGORY_LIST":   "categories:list",
    "CATEGORY_DETAIL": "categories:detail:{slug}",
    "TAG_LIST":        "tags:list",
    "TAG_DETAIL":      "tags:detail:{slug}",
    "AUTHOR_PROFILE":  "users:profile:{slug}",
}

CACHE_TTL = {
    "DEFAULT":         300,
    "ARTICLE_DETAIL":  600,
    "ARTICLE_LIST":    120,
    "TOP_STORIES":     60,
    "BREAKING_NEWS":   30,
    "FEATURED":        300,
    "CATEGORY_LIST":   600,
    "CATEGORY_DETAIL": 300,
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE     = "Africa/Harare"
USE_I18N      = True
USE_TZ        = True

STATIC_URL  = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL  = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Security defaults — strict in production, relaxed in dev/test.
SECURE_SSL_REDIRECT = _env_flag("SECURE_SSL_REDIRECT", default=_PRODUCTION)
SESSION_COOKIE_SECURE = _env_flag("SESSION_COOKIE_SECURE", default=_PRODUCTION)
CSRF_COOKIE_SECURE = _env_flag("CSRF_COOKIE_SECURE", default=_PRODUCTION)
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_HSTS_SECONDS = int(
    os.environ.get("SECURE_HSTS_SECONDS", "31536000" if _PRODUCTION else "0")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_flag(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=bool(_PRODUCTION and SECURE_HSTS_SECONDS),
)
SECURE_HSTS_PRELOAD = _env_flag(
    "SECURE_HSTS_PRELOAD",
    default=bool(_PRODUCTION and SECURE_HSTS_SECONDS),
)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# CORS
_CORS_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _CORS_ORIGINS:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _CORS_ORIGINS.split(",") if o.strip()]
else:
    CORS_ALLOW_ALL_ORIGINS = DEBUG

CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "core.throttling.RoleBasedThrottle",
        "core.throttling.BurstRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon":          "500/hour",
        "contributor":   "1000/hour",
        "author":        "2000/hour",
        "editor":        "5000/hour",
        "senior_editor": "10000/hour",
        "admin":         "20000/hour",
        "strict_anon":   "10/hour",
    },
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardResultsPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.structured_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":    timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME":   timedelta(days=7),
    "ROTATE_REFRESH_TOKENS":    True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES":        ("Bearer",),
    "TOKEN_OBTAIN_SERIALIZER":  "core.jwt.GraniteTokenObtainPairSerializer",
}

SPECTACULAR_SETTINGS = {
    "TITLE":                "The Granite Post API",
    "DESCRIPTION":          "Editorial CMS API for The Granite Post news platform.",
    "VERSION":              "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX":   "/api/v1/",
}

ADMIN_SITE_HEADER = "The Granite Post — Editorial CMS"
ADMIN_SITE_TITLE  = "Granite Post Admin"
ADMIN_INDEX_TITLE = "Newsroom Administration"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            # request_id is injected by StructuredLoggingMiddleware; the
            # AddRequestDefaults filter ensures the field is always present.
            "format": "{levelname} {asctime} {name} [{request_id}] {message}",
            "style":  "{",
        },
    },
    "filters": {
        "request_defaults": {
            "()": "core.logging_utils.AddRequestDefaults",
        },
    },
    "handlers": {
        "console": {
            "class":     "logging.StreamHandler",
            "formatter": "verbose",
            "filters":   ["request_defaults"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level":    "WARNING",
    },
    "loggers": {
        "django":                {"handlers": ["console"], "level": "INFO", "propagate": False},
        "core":                  {"handlers": ["console"], "level": "INFO", "propagate": False},
        "core.cloudflare":       {"handlers": ["console"], "level": "INFO", "propagate": False},
        "core.cloudflare_purge": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # One entry per app — all at INFO so DEBUG cache/signal noise is suppressed.
        "accounts":      {"handlers": ["console"], "level": "INFO", "propagate": False},
        "advertising":   {"handlers": ["console"], "level": "INFO", "propagate": False},
        "articles":      {"handlers": ["console"], "level": "INFO", "propagate": False},
        "audit":         {"handlers": ["console"], "level": "INFO", "propagate": False},
        "analytics":     {"handlers": ["console"], "level": "INFO", "propagate": False},
        "comments":      {"handlers": ["console"], "level": "INFO", "propagate": False},
        "media_assets":  {"handlers": ["console"], "level": "INFO", "propagate": False},
        "newsletter":    {"handlers": ["console"], "level": "INFO", "propagate": False},
        "notifications": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "redirects":     {"handlers": ["console"], "level": "INFO", "propagate": False},
        "search":        {"handlers": ["console"], "level": "INFO", "propagate": False},
        "sections":      {"handlers": ["console"], "level": "INFO", "propagate": False},
        "subscriptions": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "users":         {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

CELERY_BROKER_URL            = "memory://" if _TESTING else os.environ.get("REDIS_URL", "memory://")
CELERY_RESULT_BACKEND        = "cache+memory://"
# Eager mode: always on for the test runner so tasks execute synchronously
# in tests without a broker.  In all other environments it is off by default
# — set CELERY_TASK_ALWAYS_EAGER=true in .env only for local dev convenience
# when you are not running a Celery worker.  Production must never set this.
CELERY_TASK_ALWAYS_EAGER     = _TESTING or _env_flag("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TIMEZONE              = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    # Passive unless celery beat is running; safe in dev, required in production.
    "subscriptions-check-expired-daily": {
        "task": "subscriptions.tasks.check_expired_subscriptions",
        "schedule": crontab(hour=0, minute=10),
    },
    "subscriptions-queue-renewal-reminders-daily": {
        "task": "subscriptions.tasks.queue_renewal_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
}
_validate_celery_settings(production=_PRODUCTION, broker_url=CELERY_BROKER_URL)

# ---------------------------------------------------------------------------
# Cloudflare CDN
# ---------------------------------------------------------------------------

# Tell Django to trust X-Forwarded-Proto from upstream proxies (Cloudflare)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST    = True

# Published Cloudflare IPv4 + IPv6 egress ranges.
# Keep in sync with https://www.cloudflare.com/ips/
CLOUDFLARE_IPS = [
    # IPv4
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    # IPv6
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]

# Cache-purge API credentials (set in .env — safe to leave blank in dev)
CLOUDFLARE_ZONE_ID   = os.environ.get("CLOUDFLARE_ZONE_ID",   "")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")

# Canonical public URL used when building absolute URLs for cache purge
SITE_URL = os.environ.get("SITE_URL", "https://thegranite.co.zw").rstrip("/")
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL",
    "http://localhost:3000" if DEBUG else SITE_URL,
).rstrip("/")

# Email delivery
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    (
        "django.core.mail.backends.locmem.EmailBackend"
        if _TESTING else
        "django.core.mail.backends.console.EmailBackend"
        if DEBUG else
        "django.core.mail.backends.smtp.EmailBackend"
    ),
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@thegranite.co.zw")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_flag("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = _env_flag("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))
_validate_email_settings(
    production=_PRODUCTION,
    email_host=EMAIL_HOST,
    email_backend=EMAIL_BACKEND,
)

# ---------------------------------------------------------------------------
# Paynow Zimbabwe payment gateway
PAYNOW_INTEGRATION_ID  = os.environ.get("PAYNOW_INTEGRATION_ID", "")
PAYNOW_INTEGRATION_KEY = os.environ.get("PAYNOW_INTEGRATION_KEY", "")
PAYNOW_RETURN_URL      = os.environ.get(
    "PAYNOW_RETURN_URL",
    "https://thegranite.co.zw/subscription/success/",
)
PAYNOW_RESULT_URL      = os.environ.get(
    "PAYNOW_RESULT_URL",
    "https://thegranite.co.zw/api/v1/subscriptions/paynow-callback/",
)
