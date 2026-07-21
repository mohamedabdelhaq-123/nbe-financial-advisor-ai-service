"""Shared fixtures for the logging-setup integration tests.

Builds a minimal, isolated FastAPI app wired with the real
RequestLoggingMiddleware — deliberately not the full app.main:app — so these
tests exercise the middleware + structlog pipeline end-to-end via real HTTP
requests without any of the other feature slices' setup/auth requirements.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import get_logger
from app.core.request_logging import RequestLoggingMiddleware

logger = get_logger(__name__)


def build_logging_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ok")
    def ok():
        return {"status": "ok"}

    @app.get("/boom")
    def boom():
        raise ValueError("kaboom")

    @app.get("/fanout")
    async def fanout():
        async def _chunk(index: int) -> None:
            logger.info("chunk_processed", chunk_index=index)

        await asyncio.gather(*(_chunk(i) for i in range(3)))
        return {"status": "ok"}

    return app


@pytest.fixture
def logging_test_app() -> FastAPI:
    return build_logging_test_app()


@pytest.fixture
def logging_test_client(logging_test_app: FastAPI) -> TestClient:
    return TestClient(logging_test_app, raise_server_exceptions=False)
