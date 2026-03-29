from django.apps import AppConfig


class SearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "search"
    verbose_name       = "Granite Post — Search"

    def ready(self) -> None:
        import search.signals  # noqa: F401
