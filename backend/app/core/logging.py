"""Structured JSON logging with mandatory secret redaction.

Every log event passes through :func:`redact`, which masks values whose *key* looks
sensitive and scrubs bearer tokens / long secrets embedded in strings.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|totp|otp|pin|api[_-]?key|authorization|cookie|"
    r"session|credential|private[_-]?key|master[_-]?key|code)",
    re.IGNORECASE,
)
_SAFE_KEYS = frozenset({"session_id", "status_code", "error_code", "event_code"})
_BEARER = re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")


def _scrub_string(value: str) -> str:
    value = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
    return _JWT.sub(REDACTED, value)


def redact(value: Any, key: str | None = None) -> Any:
    if key is not None and key not in _SAFE_KEYS and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        return _scrub_string(value)
    return value


def _redact_processor(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in event_dict.items():
        if key == "event":
            out[key] = _scrub_string(value) if isinstance(value, str) else value
        else:
            out[key] = redact(value, key)
    return out


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Quieten libraries that might echo request details.
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="%(message)s")


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
