"""
settings.py — The Granite Post CMS

Environment variables (set in .env / deployment secrets):
  SECRET_KEY            — Django secret key (required in production)
  DEBUG                 — "true" or "false" (default: false)
  ALLOWED_HOSTS         — comma-separated hostnames
  DATABASE_URL          — postgres://user:pass@host:5432/dbname
  REDIS_URL             — redis://host:6379/0
  CORS_ALLOWED_ORIGINS  — comma-separated origins (e.g. https://thegranitepost.com)
  MAINTENANCE_MODE      — "true" to enable maintenance mode (default: false)
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Core security
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-change-me-in-production",
)

DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

MAINTENANCE_MODE = os.environ.get("MAINTENANCE_MODE", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",

    # Project apps
    "core",
    "articles",
    "users",
    "analytics.apps.AnalyticsConfig",
    "comments.apps.CommentsConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # Custom
    "core.middleware.StructuredLoggingMiddleware",
    "core.middleware.RequestTimingMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
    "core.middleware.MaintenanceModeMiddleware",
    
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION  = "config.asgi.application"

AUTH_USER_MODEL = "users.StaffUser"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

if _DATABASE_URL:
    import dj_database_url  # pip install dj-database-url
    DATABASES = {"default": dj_database_url.parse(_DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Cache (Redis in production, local-memory for dev/SQLite)
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "")

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND":   "django.core.cache.backends.redis.RedisCache",
            "LOCATION":  REDIS_URL,
            "KEY_PREFIX": "granite",
            "OPTIONS":   {"socket_connect_timeout": 5},
        },
        "throttle": {
            "BACKEND":   "django.core.cache.backends.redis.RedisCache",
            "LOCATION":  REDIS_URL,
            "KEY_PREFIX": "granite:throttle",
            "OPTIONS":   {"socket_connect_timeout": 5},
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

# ---------------------------------------------------------------------------
# Cache key registry and TTLs
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE     = "Africa/Harare"
USE_I18N      = True
USE_TZ        = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL  = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

_CORS_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "")

if _CORS_ORIGINS:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _CORS_ORIGINS.split(",") if o.strip()]
else:
    CORS_ALLOW_ALL_ORIGINS = DEBUG

CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

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
        # Sustained hourly caps per role
        "anon":          "500/hour",
        "contributor":   "1000/hour",
        "author":        "2000/hour",
        "editor":        "5000/hour",
        "senior_editor": "10000/hour",
        "admin":         "20000/hour",
        # Login/sensitive endpoints
        "strict_anon":   "10/hour",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.structured_exception_handler",
}

# ---------------------------------------------------------------------------
# JWT (SimpleJWT)
# ---------------------------------------------------------------------------

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":    timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME":   timedelta(days=7),
    "ROTATE_REFRESH_TOKENS":    True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES":        ("Bearer",),
    "TOKEN_OBTAIN_SERIALIZER":  "core.jwt.GraniteTokenObtainPairSerializer",
}

# ---------------------------------------------------------------------------
# drf-spectacular (OpenAPI 3 schema + Swagger UI)
# ---------------------------------------------------------------------------

SPECTACULAR_SETTINGS = {
    "TITLE":       "The Granite Post API",
    "DESCRIPTION": "Editorial CMS API for The Granite Post news platform.",
    "VERSION":     "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX":   "/api/v1/",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class":     "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level":    "WARNING",
    },
    "loggers": {
        "django":   {"handlers": ["console"], "level": "INFO",  "propagate": False},
        "core":     {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "articles": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "users":    {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL        = os.environ.get("REDIS_URL", "memory://")
CELERY_RESULT_BACKEND    = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER     = True   # run tasks inline (no broker) — safe for tests & dev
CELERY_TASK_EAGER_PROPAGATES = False  # don't propagate task errors to caller in eager mode
