"""
Alembic environment configuration for the NBE AI service.

SCOPE BOUNDARY — IMPORTANT:
    This service migrates ONLY its own database. `target_metadata` is
    `OwnBase.metadata` and nothing else. The backend-owned tables live behind
    `app.backend_db.BackendBase`, which is deliberately NOT imported here, so
    Alembic can never create, alter, or drop them.

Connection is built from environment variables (via the app settings) — no
credentials are hardcoded here or in alembic.ini.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

# Own-DB metadata only. Importing OwnBase registers the service's models.
from app.core.db import OwnBase  # noqa: F401 — metadata registration side-effect

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = OwnBase.metadata


def run_migrations_offline() -> None:
    """Emit SQL without a live DB connection."""
    context.configure(
        url=settings.own_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database using an async engine."""
    connectable = create_async_engine(settings.own_database_url)
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
