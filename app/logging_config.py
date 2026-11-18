"""Structured JSON logging.

Every transaction / payment state change is emitted as a single JSON line so the
history of a payment can be reconstructed from the logs (cadrage metier: "Chaque
transaction est loggee").
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# Set per HTTP request by the middleware. Background resolution tasks are created while
# handling the request, so they inherit it and their logs stay linked to the original call.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = set(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        # Anything passed via `logger.info("...", extra={...})` lands here.
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever `sys.stdout` is *now*, so output survives stdout being swapped."""

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, value) -> None:  # StreamHandler.__init__ assigns it; ignore
        pass


def configure_logging(level: int | str = logging.INFO) -> None:
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
