"""
Logging for the API and the Celery workers.

* JSON lines in production (one object per line, ready for Loki/ELK/CloudWatch), readable
  text in development. Override with LOG_FORMAT=json|text.
* Correlation context: `log_context(request_id=..., run_id=..., source=...)` binds values
  to the current async task / thread via contextvars, and every log record emitted inside
  it carries them, including records from libraries.
"""
import contextlib
import contextvars
import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Iterator

from app.core.config import settings

# Keys that may be bound to the logging context. Kept explicit so log schemas stay stable.
CONTEXT_KEYS = ("request_id", "run_id", "source", "task_id", "task_name", "user_id")

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("radar_log_context", default={})


def bind_context(**values: Any) -> contextvars.Token:
    """Adds values to the current logging context. Returns a token for `reset_context`."""
    unknown = set(values) - set(CONTEXT_KEYS)
    if unknown:
        raise ValueError(f"Unknown log context keys: {sorted(unknown)}")
    merged = {**_context.get(), **{k: str(v) for k, v in values.items() if v is not None}}
    return _context.set(merged)


def reset_context(token: contextvars.Token) -> None:
    _context.reset(token)


def get_context() -> dict[str, Any]:
    return dict(_context.get())


@contextlib.contextmanager
def log_context(**values: Any) -> Iterator[None]:
    token = bind_context(**values)
    try:
        yield
    finally:
        reset_context(token)


class ContextFilter(logging.Filter):
    """Copies the bound context onto every record (as attributes) so formatters can use it."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _context.get()
        for key in CONTEXT_KEYS:
            if not hasattr(record, key):
                setattr(record, key, ctx.get(key))
        return True


_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", *CONTEXT_KEYS}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        # Structured extras passed via logger.info(..., extra={...}).
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s [%(levelname)s] %(name)s: %(message)s%(ctx)s")

    def format(self, record: logging.LogRecord) -> str:
        parts = [f"{k}={getattr(record, k)}" for k in CONTEXT_KEYS if getattr(record, k, None)]
        record.ctx = f"  [{' '.join(parts)}]" if parts else ""
        return super().format(record)


def _resolve_format() -> str:
    if settings.LOG_FORMAT:
        return settings.LOG_FORMAT.lower()
    return "json" if settings.is_production else "text"


def setup_logging() -> None:
    """Configures the root logger. Safe to call more than once."""
    level_name = (settings.LOG_LEVEL or ("DEBUG" if settings.DEBUG else "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if _resolve_format() == "json" else TextFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level_name)

    # Route uvicorn/celery through our handler; the API logs its own access lines
    # (with request ids and timings) so uvicorn's are silenced.
    for name in ("uvicorn", "uvicorn.error", "celery", "celery.task"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True

    for noisy in ("asyncio", "httpx", "httpcore", "urllib3", "botocore", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # Library internals that are pure noise at DEBUG (bootstep traces, a timer line every
    # second, a redis line per connection). DEBUG still applies to our own `radar.*` loggers.
    for chatty in ("kombu", "redis", "celery.bootsteps", "celery.pool", "celery.worker", "celery.beat", "amqp"):
        logging.getLogger(chatty).setLevel(logging.INFO)


logger = logging.getLogger("radar")
