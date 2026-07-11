"""
Shared test setup.

The whole suite runs in mock mode (USE_MOCK_LLM=1) -- no API key, no model or
network calls. Environment must be set before the app is imported so config
validation and the mock short-circuit see it.

No fixture performs real LLM or embedder calls.
"""

import hashlib
import os

os.environ.setdefault("USE_MOCK_LLM", "1")
os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("OPENAI_API_KEY", "__mock__")
os.environ.setdefault("MODEL_NAME", "gpt-4o-mini")
os.environ.setdefault("AI_SERVICE_TOKEN", "test-token-for-ci")

from shutil import which

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app

TOKEN = os.environ["AI_SERVICE_TOKEN"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="session")
def own_pg():
    pytest.importorskip("testcontainers.postgres")

    if not which("docker"):
        pytest.skip("Docker not available")

    from testcontainers.postgres import PostgresContainer

    from app.backend_db import BackendBase
    from app.core.db import OwnBase

    with PostgresContainer("postgres:16-alpine") as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        db_url = f"postgresql+asyncpg://{pg.username}:{pg.password}@{host}:{port}/{pg.dbname}"

        engine = create_async_engine(db_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def _run_migrations():
            async with engine.begin() as conn:
                await conn.run_sync(OwnBase.metadata.create_all)
                await conn.run_sync(BackendBase.metadata.create_all)

        import asyncio

        asyncio.get_event_loop().run_until_complete(_run_migrations())

        yield session_factory

        engine.sync_engine.dispose()


@pytest.fixture
def mock_embedder(monkeypatch):
    def _mock_embed_texts(texts: list[str]) -> list[list[float]]:
        dim = 768
        results = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            vec = [((h[i % len(h)] + i) / 255.0) for i in range(dim)]
            norm = sum(v * v for v in vec) ** 0.5
            results.append([v / norm for v in vec])
        return results

    monkeypatch.setattr("app.features.embed.service.embed_texts", _mock_embed_texts)
    return _mock_embed_texts


@pytest.fixture
def mock_backend_session(own_pg):
    async def _seed_rows(rows: list[dict]) -> None:
        async with own_pg() as session:
            from app.backend_db.models import Transaction

            for r in rows:
                session.add(Transaction(**r))
            await session.commit()

    return _seed_rows
