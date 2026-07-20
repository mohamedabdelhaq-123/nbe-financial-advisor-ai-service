"""Unit tests for correlation-ID contextvar binding used by RequestLoggingMiddleware.

End-to-end HTTP-level behavior (access-log lines, concurrent-request
isolation, asyncio.gather fan-out propagation) is covered by the
integration tests under tests/integration/.
"""

import uuid

import structlog
from structlog.testing import capture_logs

from app.core.logging import SHARED_PROCESSORS, get_logger


def _fresh_logger():
    return get_logger(f"tests.core.test_request_logging.{uuid.uuid4().hex}")


def _capture_logs():
    return capture_logs(processors=SHARED_PROCESSORS)


def test_bound_correlation_id_present_on_log_entries():
    logger = _fresh_logger()
    correlation_id = str(uuid.uuid4())

    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    try:
        with _capture_logs() as entries:
            logger.info("inside_request_scope")
    finally:
        structlog.contextvars.clear_contextvars()

    assert entries[0]["correlation_id"] == correlation_id


def test_correlation_id_absent_after_clear():
    logger = _fresh_logger()

    structlog.contextvars.bind_contextvars(correlation_id=str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()

    with _capture_logs() as entries:
        logger.info("outside_request_scope")

    assert "correlation_id" not in entries[0]
