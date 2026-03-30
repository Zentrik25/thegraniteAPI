"""
smoke_test.py — Dependency import smoke test.

Verifies that every runtime-critical third-party package declared in
requirements.txt can actually be imported.  Intended to be run as part
of CI after `pip install -r requirements.txt` so that a missing package
fails the build before the app ever starts.

Usage:
    python smoke_test.py
    # exit 0 on success, exit 1 with a summary of missing packages on failure

This file has no Django dependency — it can be run before `manage.py`
and before the database is available.
"""

import importlib
import sys

# Map: human-readable label → importable module name.
# Where the pip package name differs from the import name, the import
# name is what matters at runtime.
REQUIRED_IMPORTS = {
    # Core framework
    "Django":                    "django",
    "djangorestframework":       "rest_framework",
    "simplejwt":                 "rest_framework_simplejwt",
    "drf-spectacular":           "drf_spectacular",
    "django-cors-headers":       "corsheaders",
    # Database
    "psycopg2-binary":           "psycopg2",
    "dj-database-url":           "dj_database_url",
    # Cache / broker
    "redis":                     "redis",
    "celery":                    "celery",
    # Image processing (media_assets validators)
    "Pillow":                    "PIL",
    # Web push notifications (notifications.tasks)
    "pywebpush":                 "pywebpush",
    # S3 / R2 media storage (activated via USE_S3=true)
    "django-storages":           "storages",
    "boto3":                     "boto3",
    # Payment gateway (subscriptions.paynow_client)
    "paynow":                    "paynow",
    # Static files
    "whitenoise":                "whitenoise",
    # Production WSGI server
    "gunicorn":                  "gunicorn",
}


def main() -> int:
    missing = []
    for label, module in REQUIRED_IMPORTS.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(f"  MISSING  {label:30s} (import {module})")

    if missing:
        print("smoke_test: FAILED — the following packages are not importable:\n")
        for line in missing:
            print(line)
        print(
            f"\n{len(missing)} package(s) missing."
            " Run: pip install -r requirements.txt"
        )
        return 1

    print(f"smoke_test: OK — all {len(REQUIRED_IMPORTS)} runtime packages importable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
