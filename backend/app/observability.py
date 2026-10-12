"""Structured logging and request-scoped correlation ids.

Logs are JSON in every environment except development (where a human-readable line is far
more useful). Customer coordinates and quote locations are deliberately excluded from log
records; only ids, codes and timings are recorded. See ``REDACT_KEYS``.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

#: Keys never written to logs, even if a caller passes them in an extra field.
REDACT_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "api_key",
        "authorization",
        "cookie",
        "position",
        "latitude",
        "longitude",
        "lat",
        "lng",
    }
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = _redact(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", "-")
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name:<34} "
            f"[{rid}] {record.getMessage()}"
        )
        extras = getattr(record, "extra_fields", None)
        if extras:
            base += " " + " ".join(f"{k}={_redact(k, v)!r}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _redact(key: str, value: Any) -> Any:
    if key.lower() in REDACT_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {k: _redact(k, v) for k, v in value.items()}
    return value


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else ConsoleFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Third-party noise that hides our own request logs.
    for noisy in ("uvicorn.access", "httpx", "httpcore", "aiosqlite", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").addFilter(RequestIdFilter())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    """Log a structured event. ``extra_fields`` is what ends up as JSON keys."""
    safe = {k: _redact(k, v) for k, v in fields.items()}
    logger.log(level, message, extra={"extra_fields": safe})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates ``X-Request-ID`` and logs the outcome of every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id")
        request_id = incoming if incoming and len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id
        logger = get_logger("app.http")
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log_event(
                logger,
                logging.ERROR,
                "request failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            raise
        finally:
            request_id_ctx.reset(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        level = logging.WARNING if response.status_code >= 500 else logging.INFO
        log_event(
            logger,
            level,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response


def iter_request_ids() -> Iterator[str]:  # pragma: no cover - convenience for debugging
    yield request_id_ctx.get()
