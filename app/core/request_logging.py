"""Per-request correlation ID binding and structured access logging.

Generates one correlation ID per inbound request (this service is Django's
only caller and no shared request-ID header contract exists between them —
see specs/012-structured-logging-setup/spec.md Assumptions), binds it via
`structlog.contextvars` so every log line emitted while handling the
request — including work spawned via `asyncio.gather` fan-out in the chat
and ingestion slices — carries it automatically, then logs one access-log
line per completed request.
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        structlog.contextvars.bind_contextvars(correlation_id=str(uuid.uuid4()))
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
