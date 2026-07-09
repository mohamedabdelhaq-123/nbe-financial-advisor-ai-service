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

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class OwnBase(DeclarativeBase):
    """Declarative base for all service-owned models (the Alembic target)."""


own_engine = create_async_engine(settings.own_database_url, pool_pre_ping=True)
OwnSession = async_sessionmaker(own_engine, expire_on_commit=False)


async def get_own_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession bound to the own database."""
    async with OwnSession() as session:
        yield session
