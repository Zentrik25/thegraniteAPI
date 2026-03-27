from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "analytics"
    verbose_name       = "Granite Post — Analytics"

    def ready(self) -> None:
        import analytics.signals  # noqa: F401
