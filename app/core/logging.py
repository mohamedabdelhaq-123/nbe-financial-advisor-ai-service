"""Structured logging setup — one JSON object per line to stdout.

Configures structlog so every log call, whether issued through
`get_logger()` or through stdlib `logging` (uvicorn, sqlalchemy, etc.),
renders through the same processor pipeline: UTC timestamp, level, logger
name, correlation-ID binding (via `structlog.contextvars`, bound per-request
by `app.core.request_logging`), and the redaction backstop below. Per
Constitution Principle III, redaction is unconditional — it is not a
per-feature opt-in.
"""

import logging
import sys

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings

_REDACTED = "[REDACTED]"
_DENYLISTED_KEYS = {"api_key", "token", "password", "authorization"}
_DENYLISTED_SUFFIXES = ("_secret", "_key")


def _redact_sensitive_fields(
    _logger: object, _method_name: str, event_dict: EventDict
) -> EventDict:
    for key in event_dict:
        if key in _DENYLISTED_KEYS or key.endswith(_DENYLISTED_SUFFIXES):
            event_dict[key] = _REDACTED
    return event_dict


# Public so tests can pass it to `structlog.testing.capture_logs(processors=...)`,
# which otherwise disables all configured processors.
SHARED_PROCESSORS: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
    structlog.processors.dict_tracebacks,
    _redact_sensitive_fields,
]


class _StdoutHandler(logging.StreamHandler):
    """Always writes to the *current* `sys.stdout`, not the object bound at
    handler-construction time — otherwise output silently stops being
    visible to whatever most recently redirected `sys.stdout` (notably
    pytest, which re-redirects it per test)."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _value: object) -> None:
        pass


def configure() -> None:
    """Wire structlog and stdlib `logging` to emit one JSON object per line.

    Idempotent — safe to call more than once (e.g. once per test app
    instantiation).
    """
    structlog.configure(
        processors=[
            *SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=SHARED_PROCESSORS,
    )
    handler = _StdoutHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.log_level.upper())

    # Uvicorn's own dictConfig gives "uvicorn", "uvicorn.error", and
    # "uvicorn.access" their own handlers with propagate=False, which would
    # otherwise bypass this JSON/redaction pipeline entirely for every
    # startup, shutdown, error, and access-log message it emits.
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    if settings.log_debug_include_raw_content:
        get_logger(__name__).warning(
            "raw_content_logging_enabled",
            detail=(
                "LOG_DEBUG_INCLUDE_RAW_CONTENT is true — raw LLM prompt/completion and "
                "DB query content may appear in DEBUG-level logs. Never enable in production."
            ),
        )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Shared entry point for every feature slice — replaces `logging.getLogger`."""
    return structlog.get_logger(name)


def raw_content_fields(**fields: object) -> dict[str, object]:
    """Return `fields` only when raw debug-content logging is explicitly enabled.

    Call sites logging LLM prompts/completions or DB query content MUST route
    them through this helper instead of passing them directly, so FR-011's
    default-off, explicit-opt-in guarantee holds regardless of `log_level`.
    """
    if settings.log_debug_include_raw_content:
        return fields
    return {}
