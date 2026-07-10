"""
Backend (Django-owned) database — READ-ONLY.

This service reads specific backend tables and NEVER writes them. Enforcement is
layered:

  * `BackendBase` is a SEPARATE declarative base and is deliberately excluded
    from Alembic's `target_metadata`, so migrations can never touch these tables.
  * The connection uses a dedicated read-only Postgres role (requested from
    backend/infra), so the database itself rejects writes.
  * The application defines no write paths against this Base.

The engine is created lazily: it is built only when the backend DB is
configured, so unit tests and CI (which fixture/mock backend data) need no live
backend. Backend tables are represented as generated typed models in
`app.backend_db.models` — regenerated directly from the live read-only backend by
`scripts/gen_backend_models.py` (never hand-edited; see Constitution Principle IV)
— a shared contract used across feature slices.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class BackendBase(DeclarativeBase):
    """Declarative base for read-only backend models. Excluded from Alembic."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _ensure_engine() -> async_sessionmaker[AsyncSession]:
    """Build the read-only engine on first use, or fail loudly if unconfigured."""
    global _engine, _sessionmaker
    if _sessionmaker is None:
        url = settings.backend_database_url
        if url is None:
            raise RuntimeError(
                "Backend database is not configured. Set BACKEND_DB_HOST/NAME/USER "
                "(read-only role) to enable read access to backend-owned tables."
            )
        _engine = create_async_engine(url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def get_backend_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a READ-ONLY AsyncSession on the backend DB."""
    factory = _ensure_engine()
    async with factory() as session:
        yield session
