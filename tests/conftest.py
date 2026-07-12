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
# Dummy placeholders so config's fail-fast check passes offline; real values
# (if a developer/CI exports them before running pytest) are left untouched
# by setdefault and picked up by the real_s3_storage_env fixture below.
os.environ.setdefault("STORAGE_S3_BUCKET", "test-bucket")
os.environ.setdefault("STORAGE_S3_ACCESS_KEY", "test-access-key")
os.environ.setdefault("STORAGE_S3_SECRET_KEY", "test-secret-key")

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
def own_db_url():
    pytest.importorskip("testcontainers.postgres")

    if not which("docker"):
        pytest.skip("Docker not available")

    import sqlalchemy as sa
    from sqlalchemy.pool import NullPool
    from testcontainers.postgres import PostgresContainer

    from app.core.db import OwnBase

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        url = f"postgresql+asyncpg://{pg.username}:{pg.password}@{host}:{port}/{pg.dbname}"

        async def _run_migrations():
            from pgvector.sqlalchemy import Vector

            engine = create_async_engine(url, poolclass=NullPool)

            saved = {}
            for table in OwnBase.metadata.tables.values():
                for col in table.columns:
                    if isinstance(col.type, Vector):
                        saved[col] = col.type
                        col.type = sa.LargeBinary()

            try:
                async with engine.begin() as conn:
                    await conn.run_sync(OwnBase.metadata.create_all)
                    await conn.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
                    await conn.execute(
                        sa.text(
                            "CREATE TABLE IF NOT EXISTS transactions ("
                            "id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), "
                            "transaction_date DATE NOT NULL, "
                            "amount NUMERIC(14,2) NOT NULL, "
                            "currency VARCHAR(10) NOT NULL DEFAULT 'EGP', "
                            "is_recurring BOOLEAN NOT NULL DEFAULT FALSE, "
                            "source VARCHAR(20) NOT NULL DEFAULT 'statement', "
                            "created_at TIMESTAMP WITH TIME ZONE NOT NULL "
                            "DEFAULT NOW(), "
                            "account_id UUID NOT NULL, "
                            "user_id UUID NOT NULL, "
                            "merchant_raw VARCHAR(500), "
                            "merchant_normalized VARCHAR(255), "
                            "category VARCHAR(100), "
                            "confidence_score NUMERIC(4,3), "
                            "balance NUMERIC(14,2), "
                            "transaction_type VARCHAR(20), "
                            "extra_fields JSONB, "
                            "embedding BYTEA, "
                            "statement_id UUID"
                            ")"
                        )
                    )
            finally:
                for col, orig in saved.items():
                    col.type = orig

            await engine.dispose()

        import asyncio

        asyncio.run(_run_migrations())

        yield url


@pytest.fixture
async def own_pg(own_db_url):
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(own_db_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def mock_embedder(monkeypatch):
    async def _mock_embed_texts(texts: list[str]) -> list[list[float]]:
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


@pytest.fixture
def real_s3_storage_env(monkeypatch):
    """Point `settings` at a real, already-running S3-compatible instance.

    Skips unless STORAGE_S3_ENDPOINT_URL/BUCKET/ACCESS_KEY/SECRET_KEY are all
    set in the real environment (not the dummy defaults above), keeping the
    default test run fully offline per the mock-first constitution principle.
    """
    endpoint = os.environ.get("STORAGE_S3_ENDPOINT_URL")
    bucket = os.environ.get("STORAGE_S3_BUCKET")
    access_key = os.environ.get("STORAGE_S3_ACCESS_KEY")
    secret_key = os.environ.get("STORAGE_S3_SECRET_KEY")
    if not (endpoint and bucket and access_key and secret_key):
        pytest.skip("Real STORAGE_S3_* env vars not configured")

    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_s3_endpoint_url", endpoint)
    monkeypatch.setattr(settings, "storage_s3_bucket", bucket)
    monkeypatch.setattr(settings, "storage_s3_access_key", access_key)
    monkeypatch.setattr(settings, "storage_s3_secret_key", secret_key)
    monkeypatch.setattr(
        settings, "storage_s3_region", os.environ.get("STORAGE_S3_REGION", "us-east-1")
    )
