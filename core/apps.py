import logging

from django.apps import AppConfig

logger = logging.getLogger("core")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Granite Post — Core Infrastructure"

    def ready(self) -> None:
        import core.signals  # noqa: F401
        self._warn_if_memory_broker()

    def _warn_if_memory_broker(self) -> None:
        """
        Log a WARNING at startup when Celery is using the memory:// broker
        and eager mode is off.

        In this state tasks are enqueued in-process and only consumed if a
        Celery worker is running inside the same process — which is never true
        for a normal gunicorn/Django deployment.  The warning is intentionally
        non-fatal: local dev without Redis is valid when eager mode is enabled
        or when no async tasks are exercised.

        Skipped in:
          - test runs (CELERY_TASK_ALWAYS_EAGER=True, tasks are synchronous)
          - production (startup validation already blocks memory:// there)
        """
        from django.conf import settings as s

        eager = getattr(s, "CELERY_TASK_ALWAYS_EAGER", False)
        if eager:
            return  # test/eager-dev: tasks are synchronous, no broker needed

        broker = getattr(s, "CELERY_BROKER_URL", "")
        if broker.startswith("memory://"):
            logger.warning(
                "Celery broker is configured as memory:// and eager mode is "
                "off. Tasks dispatched with .delay() or .apply_async() will "
                "be queued in-process and lost on restart unless a Celery "
                "worker is running. Set REDIS_URL or set "
                "CELERY_TASK_ALWAYS_EAGER=true for local dev."
            )
