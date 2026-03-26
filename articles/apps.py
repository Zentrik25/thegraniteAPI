"""
apps.py — AppConfig for The Granite Post articles app.
"""

from django.apps import AppConfig


class ArticlesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "articles"
    verbose_name       = "Granite Post — Articles"

    def ready(self):
        # Connect signals once the app registry is fully loaded.
        import articles.signals  # noqa: F401
