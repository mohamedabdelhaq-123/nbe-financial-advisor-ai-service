"""Unit tests for correlation-ID and current_feature contextvar binding used
by RequestLoggingMiddleware.

End-to-end HTTP-level behavior beyond current_feature (access-log lines,
concurrent-request isolation, asyncio.gather fan-out propagation) is covered
by the integration tests under tests/integration/. current_feature's
request-lifecycle reset is tested here anyway (via a minimal local app, not
app.main:app) since that behavior only exists at the middleware's dispatch
boundary — there's nothing to unit-test about it without driving a request.
"""

import uuid

import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.core.logging import SHARED_PROCESSORS, get_logger
from app.core.request_logging import RequestLoggingMiddleware, current_feature


def _fresh_logger():
    return get_logger(f"tests.core.test_request_logging.{uuid.uuid4().hex}")


def _capture_logs():
    return capture_logs(processors=SHARED_PROCESSORS)


def _build_feature_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/internal/{feature}/x")
    def internal_route(feature: str):
        return {"current_feature": current_feature.get()}

    @app.get("/health")
    def health():
        return {"current_feature": current_feature.get()}

    return app


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


def test_current_feature_reflects_active_request_path_segment():
    client = TestClient(_build_feature_test_app())

    response = client.get("/internal/chat/x")

    assert response.json()["current_feature"] == "chat"
    assert current_feature.get() is None  # reset once the request completes


def test_current_feature_none_outside_internal_prefix():
    client = TestClient(_build_feature_test_app())

    response = client.get("/health")

    assert response.json()["current_feature"] is None


def test_current_feature_resets_across_sequential_requests_with_different_paths():
    client = TestClient(_build_feature_test_app())

    first = client.get("/internal/chat/x")
    second = client.get("/internal/plan/x")

    assert first.json()["current_feature"] == "chat"
    assert second.json()["current_feature"] == "plan"
    assert current_feature.get() is None
