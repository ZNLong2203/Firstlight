"""JSON logs on stdout, carrying the Datadog trace and span ids that ddtrace injects."""

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime

_DD_FIELDS = ("dd.trace_id", "dd.span_id", "dd.service", "dd.env", "dd.version")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "status": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _DD_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, "", "0"):
                entry[field] = value
        context = getattr(record, "ctx", None)
        if isinstance(context, dict):
            for key, value in context.items():
                # Context never replaces a reserved field: Datadog reads the level from `status`.
                entry[f"ctx.{key}" if key in entry else key] = value
        if record.exc_info:
            entry["error.stack"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class ShutdownCancellations(logging.Filter):
    """On a restart uvicorn cancels the connections that never end on their own, the consoles' live
    streams and the gateways' command channels, and logs each as an error. They are closed on
    purpose, and every client reconnects, so they are logged as information instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        cancelled = bool(record.exc_info) and isinstance(record.exc_info[1], asyncio.CancelledError)  # type: ignore[index]
        if cancelled:
            record.msg, record.args, record.exc_info = "connection closed by shutdown", (), None
        if cancelled or "graceful shutdown exceeded" in record.getMessage():
            record.levelno, record.levelname = logging.INFO, "INFO"
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # One line per HTTP request would be 50 gateways x 6 per minute: requests are traced, not logged.
    for noisy in ("uvicorn.access", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").addFilter(ShutdownCancellations())
