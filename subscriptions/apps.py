"""
apps.py — App configuration for the subscriptions app.
"""

from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    """Configuration for the subscriptions app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "subscriptions"
    verbose_name = "Subscriptions"
