r"""
Minimal clean-install smoke check for runtime-critical imports.

Usage:
    .\venv\Scripts\python.exe scripts\runtime_import_smoke.py
"""

import importlib
import os
import sys
from pathlib import Path


RUNTIME_MODULES = [
    "celery",
    "paynow",
    "requests",
    "pywebpush",
    "PIL",
]

DJANGO_RUNTIME_MODULES = [
    "core.cloudflare_purge",
    "media_assets.validators",
    "notifications.tasks",
    "subscriptions.paynow_client",
]


def _import_or_exit(module_name: str) -> None:
    try:
        importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        print(f"IMPORT FAIL {module_name}: {exc}", file=sys.stderr)
        raise
    else:
        print(f"IMPORT OK {module_name}")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    for module_name in RUNTIME_MODULES:
        _import_or_exit(module_name)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()

    for module_name in DJANGO_RUNTIME_MODULES:
        _import_or_exit(module_name)

    print("Runtime import smoke check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

