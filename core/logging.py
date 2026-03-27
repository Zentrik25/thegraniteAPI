import json
import logging
import traceback
from datetime import datetime, timezone

_STDLIB_ATTRS = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
    "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "thread", "threadName",
})


class JSONFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        record.getMessage()

        log: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":     record.levelname,
            "logger":    record.name,
            "message":   record.getMessage(),
            "process":   record.process,
            "thread":    record.thread,
        }

        if record.exc_info:
            log["exception"] = "".join(traceback.format_exception(*record.exc_info))

        if record.stack_info:
            log["stack_info"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _STDLIB_ATTRS and not key.startswith("_"):
                log[key] = value

        return json.dumps(log, default=_json_default, ensure_ascii=False)


def _json_default(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
