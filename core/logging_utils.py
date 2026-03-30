import logging


def _mask_email(email: str) -> str:
    """Mask an email address for safe log output.

    ``alice@example.com`` → ``a****@example.com``
    Only the local part (before @) is redacted; the domain is kept so
    log readers can still identify the mail provider for debugging.
    """
    if not email or "@" not in email:
        return "[redacted]"
    local, domain = email.split("@", 1)
    return f"{local[:1]}****@{domain}"


class AddRequestDefaults(logging.Filter):
    """Inject default values for structured fields added by StructuredLoggingMiddleware.

    The verbose formatter references ``{request_id}`` — this filter ensures that
    field is present on every LogRecord so the formatter never raises KeyError on
    log records that were not emitted from within a request context (e.g. Celery
    tasks, management commands, startup messages).
    """

    _DEFAULTS: dict[str, str] = {"request_id": "-"}

    def filter(self, record: logging.LogRecord) -> bool:
        for key, default in self._DEFAULTS.items():
            if not hasattr(record, key):
                setattr(record, key, default)
        return True
