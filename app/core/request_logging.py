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
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

current_feature: ContextVar[str | None] = ContextVar("current_feature", default=None)

_INTERNAL_FEATURE_SEGMENT = re.compile(r"^/internal/([^/]+)")


def _feature_from_path(path: str) -> str | None:
    match = _INTERNAL_FEATURE_SEGMENT.match(path)
    return match.group(1) if match else None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        structlog.contextvars.bind_contextvars(correlation_id=str(uuid.uuid4()))
        feature_token = current_feature.set(_feature_from_path(request.url.path))
        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            logger.exception(
                "unhandled_exception",
                http_method=request.method,
                http_path=request.url.path,
            )
            raise
        finally:
            logger.info(
                "request_completed",
                http_method=request.method,
                http_path=request.url.path,
                http_status=status_code,
                duration_ms=round((time.monotonic() - start) * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
            current_feature.reset(feature_token)
