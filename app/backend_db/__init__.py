"""
Backend (Django-owned) database — READ-ONLY BY DEFAULT.

This service reads specific backend tables and, outside two narrow, Constitution-
authorized exceptions, never writes them. Enforcement is layered:

  * `BackendBase` is a SEPARATE declarative base and is deliberately excluded
    from Alembic's `target_metadata`, so migrations can never touch these tables.
  * The connection uses a dedicated `ai_readonly` Postgres role (requested from
    backend/infra) whose `default_transaction_read_only` is on, so every
    transaction is read-only unless it explicitly opts out.
  * The application defines no write paths against this Base beyond the two
    exceptions Constitution Principle IV enumerates: `transactions.embedding`
    (written by `app.features.transactions.service.embed_transactions`, which
    opts a single transaction into `SET TRANSACTION READ WRITE`) and
    `monthly_summaries` (full CRUD). Every other feature reading through this
    module stays strictly read-only.

The engine is created lazily on first use. `Settings.backend_database_url`
is non-Optional and guaranteed set at startup by `BackendDbSettings`' own
validator, so this module never has to branch on a missing URL — unit tests
and CI fixture/mock backend data bypass this engine entirely via
`monkeypatch.setattr("app.backend_db.get_backend_session", ...)`. Backend
tables are represented as generated typed models in `app.backend_db.models`
— regenerated directly from the live read-only backend by
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
    """Build the read-only engine on first use.

    No missing-config check needed — see module docstring on `backend_database_url`.
    """
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(settings.backend_database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def get_backend_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a READ-ONLY AsyncSession on the backend DB."""
    factory = _ensure_engine()
    async with factory() as session:
        yield session
