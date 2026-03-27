from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "users"
    verbose_name       = "Granite Post — Users & Staff"

    def ready(self) -> None:
        import users.signals  # noqa: F401
