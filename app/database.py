"""
SQLAlchemy base and engine for the AI service.

SCOPE BOUNDARY: This service manages ONLY its own tables.
It must never create, alter, or drop Django's tables.
All Django tables are owned exclusively by the Django backend
and must only be modified via `python manage.py migrate`.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _build_url() -> str:
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "appdb")
    user = os.environ.get("POSTGRES_USER", "appuser")
    password = os.environ.get("POSTGRES_PASSWORD", "apppass")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = _build_url()

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """
    All AI-service SQLAlchemy models inherit from this Base.
    Alembic autogenerate uses this metadata to detect schema changes.
    """

    pass
