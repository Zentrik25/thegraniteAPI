from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Granite Post — Core Infrastructure"

    def ready(self) -> None:
        import core.signals  # noqa: F401
