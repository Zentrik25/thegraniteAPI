from django.apps import AppConfig


class AdvertisingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "advertising"
    verbose_name       = "Granite Post - Advertising"

    def ready(self) -> None:
        import advertising.signals  # noqa: F401
