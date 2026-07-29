"""
Own (service-managed) database — READ-WRITE.

SCOPE BOUNDARY: this is the ONLY database this service migrates. Its metadata
(`OwnBase.metadata`) is the sole Alembic target. Backend-owned tables live
behind a separate Base in `app.backend_db` and must never be created, altered,
or dropped from here.

Own-table models live in the feature slice that owns them and import `OwnBase`
from this module.
"""

from collections.abc import AsyncIterator
from urllib.parse import quote

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class OwnBase(DeclarativeBase):
    """Declarative base for all service-owned models (the Alembic target)."""


def psycopg_conn_string() -> str:
    """Own-DB connection string in psycopg form.

    The application's own traffic runs on asyncpg (`settings.own_database_url`), but two
    libraries embedded in this service — the LangGraph checkpointer and the SAQ job queue
    — bring their own psycopg pools. They share this one builder so the credentials are
    assembled in exactly one place.

    Settings are read at call time, not import time. This module is imported early, so
    the module-level `settings` above is bound before anything that rewrites the
    environment can take effect — including tests that patch the own-DB env vars and
    `importlib.reload()` the config module to point a real connection at a
    Testcontainers instance.
    """
    from app.core.config import settings as current

    user = quote(str(current.own_db.postgres_user), safe="")
    password = quote(current.own_db.postgres_password.get_secret_value(), safe="")
    return (
        f"postgresql://{user}:{password}"
        f"@{current.own_db.postgres_host}:{current.own_db.postgres_port}"
        f"/{current.own_db.postgres_db}"
    )


own_engine = create_async_engine(settings.own_database_url, pool_pre_ping=True)
OwnSession = async_sessionmaker(own_engine, expire_on_commit=False)


async def get_own_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession bound to the own database."""
    async with OwnSession() as session:
        yield session
