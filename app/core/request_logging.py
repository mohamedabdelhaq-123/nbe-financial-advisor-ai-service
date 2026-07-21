"""Per-request correlation ID binding and structured access logging.

Generates one correlation ID per inbound request (this service is Django's
only caller and no shared request-ID header contract exists between them —
see specs/012-structured-logging-setup/spec.md Assumptions), binds it via
`structlog.contextvars` so every log line emitted while handling the
request — including work spawned via `asyncio.gather` fan-out in the chat
and ingestion slices — carries it automatically, then logs one access-log
line per completed request.

Also binds `current_feature`, a plain `contextvars.ContextVar` (not a
structlog-bound field — it's read by `app.core.observability`'s redaction
processor, not by the logging pipeline) set to the path segment right after
`/internal/`. Every feature router is mounted at `/internal/<segment>/...`
(app/main.py), so this labels every span produced while handling the
request with the originating feature/flow for Langfuse's usage dashboard
(US2, FR-006, SC-005, research.md §7) with no per-call-site wiring. Requests
outside `/internal/` (e.g. `/health`, `/ready`) leave it at its default of
`None`.
"""

import re
import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

logger = get_logger(__name__)

current_feature: ContextVar[str | None] = ContextVar("current_feature", default=None)

_INTERNAL_FEATURE_SEGMENT = re.compile(r"^/internal/([^/]+)")


def _feature_from_path(path: str) -> str | None:
    match = _INTERNAL_FEATURE_SEGMENT.match(path)
    return match.group(1) if match else None


class RequestLoggingMiddleware:
    """Pure ASGI middleware — not `BaseHTTPMiddleware`, whose `dispatch()`
    returns as soon as response headers are ready rather than after the body
    finishes sending. That breaks both `duration_ms` and exception capture
    for the chat slice's SSE `StreamingResponse` (app/features/chat/router.py),
    where the body can keep streaming long after headers are sent."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        http_method = scope["method"]
        http_path = scope["path"]
        structlog.contextvars.bind_contextvars(correlation_id=str(uuid.uuid4()))
        feature_token = current_feature.set(_feature_from_path(http_path))
        start = time.monotonic()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            # For a StreamingResponse, Starlette runs the body-sending
            # coroutine in a task-group-spawned child task; this await only
            # returns once that task group's __aexit__ has rejoined it, i.e.
            # after the full stream has actually been sent — not just headers.
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "unhandled_exception",
                http_method=http_method,
                http_path=http_path,
            )
            raise
        finally:
            # Deliberately not done from inside send_wrapper: that callable
            # may run in the child task's own context copy for a streamed
            # response, and a ContextVar token can only be reset in the
            # context it was created in.
            logger.info(
                "request_completed",
                http_method=http_method,
                http_path=http_path,
                http_status=status_code,
                duration_ms=round((time.monotonic() - start) * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
            current_feature.reset(feature_token)
