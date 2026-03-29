from django.apps import AppConfig


class RedirectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "redirects"
    verbose_name       = "Granite Post — Redirects"

    def ready(self) -> None:
        import redirects.signals  # noqa: F401