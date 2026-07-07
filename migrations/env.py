"""
Alembic environment configuration for the NBE AI service.

SCOPE BOUNDARY — IMPORTANT:
    This service manages ONLY its own tables (prefixed `ai_`).
    It must NEVER create, alter, or drop Django's tables.
    Django tables are owned exclusively by the backend repo and
    are modified only via `python manage.py migrate`.

Connection is built from environment variables — no credentials are
hardcoded here or in alembic.ini.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── bring in the AI-service model metadata ────────────────────────────────────
# Import Base so Alembic autogenerate can detect model changes.
# When the AI team adds a model, they import it here alongside Base.
from app.database import Base  # noqa: F401 — metadata registration side-effect

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ── build the DB URL from env vars — never from alembic.ini ──────────────────
def _get_url() -> str:
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "appdb")
    user = os.environ.get("POSTGRES_USER", "appuser")
    password = os.environ.get("POSTGRES_PASSWORD", "apppass")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


# ── offline mode (no DB connection; generates SQL instead) ───────────────────
def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── online mode (real DB connection; used by `alembic upgrade head`) ─────────
def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
