import os
import sys
from datetime import timedelta
from pathlib import Path

_TESTING = "test" in sys.argv


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

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
    "django-insecure-change-me-in-production",
)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

DEBUG = _env_flag("DEBUG", default=False)

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
    "subscription.apps.SubscriptionConfig",
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
            "format": "{levelname} {asctime} {name} {message}",
            "style":  "{",
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
        "django":       {"handlers": ["console"], "level": "INFO",  "propagate": False},
        "core":         {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "articles":     {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "users":        {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "analytics":    {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "comments":     {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "newsletter":   {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "search":       {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "media_assets": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}

CELERY_BROKER_URL            = "memory://" if _TESTING else os.environ.get("REDIS_URL", "memory://")
CELERY_RESULT_BACKEND        = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER     = True
CELERY_TASK_EAGER_PROPAGATES = False
