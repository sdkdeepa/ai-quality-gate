import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import get_request_id
from app.core.redaction import redact

# Every attribute a stock LogRecord carries, computed once from a
# throwaway record - anything else found on a given record is something a
# caller passed via `logger.info(msg, extra={...})`, and should be
# surfaced in the JSON payload. This is what makes "structured logs" with
# run_id/trace_id/dataset_version/policy_version/etc. actually work — see
# DECISIONS.md's Sprint 12 entry: `extra=` fields were previously silently
# dropped here, so `RequestIDMiddleware`'s own `path`/`method`/
# `status_code`/`duration_ms` never once made it into a log line despite
# being passed on every request since Sprint 1.
_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",  # added by LogRecord.getMessage(), not present until called
    "asctime",  # added by Formatter.format() only if a format string requests it
}


class JSONFormatter(logging.Formatter):
    """Renders log records as single-line JSON so they can be ingested by
    log tooling. Every string value (the message, every `extra` field,
    and any exception traceback) is run through
    `app.core.redaction.redact()` before being serialized — see that
    module's docstring for why.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS:
                continue
            payload[key] = redact(value) if isinstance(value, str) else value

        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        # default=str: a value passed via `extra=` that isn't natively
        # JSON-serializable (a Path, a set, ...) falls back to its string
        # form rather than crashing the logger itself — logging failing
        # to log is a worse outcome than a slightly-less-structured field.
        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root.handlers.clear()
    root.addHandler(handler)
