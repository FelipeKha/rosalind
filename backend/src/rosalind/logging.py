"""Structured, local, content-free logging for Rosalind.

The repo uses stdlib ``logging`` (no third-party logging dependency). This
module adds:

* context variables carried on every record through a request/run
  (``request_id``, ``audit_id``, ``account_id``, ``plan_fingerprint``,
  ``stage``; evaluation adds ``run_id`` and ``question_id``);
* a JSON formatter for deployed use, and a human formatter for local dev;
* :func:`configure_logging`, called once at process startup.

Nothing here ships data to an external service. Callers must not log query
text, keywords, addresses, subjects, bodies, snippets, or query vectors; the
search summary recorder in particular logs only names, counts, IDs and timings.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "JsonFormatter",
    "configure_logging",
    "log_context",
]

_CONTEXT_VARS: dict[str, ContextVar[str | None]] = {
    "request_id": ContextVar("rosalind_request_id", default=None),
    "audit_id": ContextVar("rosalind_audit_id", default=None),
    "account_id": ContextVar("rosalind_account_id", default=None),
    "plan_fingerprint": ContextVar("rosalind_plan_fingerprint", default=None),
    "stage": ContextVar("rosalind_stage", default=None),
    "run_id": ContextVar("rosalind_run_id", default=None),
    "question_id": ContextVar("rosalind_question_id", default=None),
}

_STANDARD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)


@contextmanager
def log_context(**fields: str | None) -> Iterator[None]:
    """Bind correlation fields for the duration of the block.

    Unknown keys are ignored, so callers can pass ``stage=...`` or ``run_id=...``
    freely.
    """
    tokens: list[tuple[ContextVar[str | None], Any]] = []
    for key, value in fields.items():
        var = _CONTEXT_VARS.get(key)
        if var is not None:
            tokens.append((var, var.set(value)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def _context_fields() -> dict[str, str]:
    return {
        name: value
        for name, var in _CONTEXT_VARS.items()
        if (value := var.get()) is not None
    }


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Render one record as a JSON object on a single line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(_context_fields())
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter that still appends correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = _extra_fields(record)
        fields.update(_context_fields())
        if not fields:
            return base
        rendered = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        return f"{base} {rendered}"


def configure_logging(
    level: str = "INFO",
    fmt: str = "console",
    *,
    log_query_text: bool = False,
) -> None:
    """Configure the ``rosalind`` logger. Idempotent.

    Local dev uses ``console``; deployed runs use ``json`` and write to stdout.
    """
    logger = logging.getLogger("rosalind")
    logger.setLevel(level.upper())
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            ConsoleFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    logger.addHandler(handler)

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level.upper(), handlers=[handler])

    if log_query_text:
        logging.getLogger("rosalind").warning(
            "log_query_text is enabled: query text will be written to logs. "
            "This is for local development only."
        )
