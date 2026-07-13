"""Service-owned category list (Alembic-managed) and category resolution.

A maintained, extensible list of known transaction categories — normalized
transactions are always assigned one of these, never arbitrary free text
(spec FR-007/FR-008).
"""

from sqlalchemy import Boolean, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import OwnBase

# Starter set seeded by migrations/versions/a6171cff73ac_add_categories_table.py.
# Exactly one row MUST have is_fallback=True (FR-008's designated fallback).
CATEGORY_SEED_DATA: list[dict] = [
    {"name": "groceries", "label": "Groceries", "is_fallback": False},
    {"name": "dining", "label": "Dining", "is_fallback": False},
    {"name": "transport", "label": "Transport", "is_fallback": False},
    {"name": "utilities", "label": "Utilities", "is_fallback": False},
    {"name": "rent", "label": "Rent", "is_fallback": False},
    {"name": "salary", "label": "Salary", "is_fallback": False},
    {"name": "transfer", "label": "Transfer", "is_fallback": False},
    {"name": "fees", "label": "Fees", "is_fallback": False},
    {"name": "entertainment", "label": "Entertainment", "is_fallback": False},
    {"name": "healthcare", "label": "Healthcare", "is_fallback": False},
    {"name": "shopping", "label": "Shopping", "is_fallback": False},
    {"name": "other", "label": "Other", "is_fallback": True},
]


class Category(OwnBase):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


async def resolve_category(session: AsyncSession, raw: str | None) -> str:
    """Resolve a raw (possibly LLM-produced) category string to a known category name.

    Case-insensitive exact match against `Category.name`; falls back to the
    seeded `is_fallback` row's name when `raw` is missing or matches nothing.
    """
    if raw:
        normalized = raw.strip().lower()
        result = await session.execute(select(Category.name).where(Category.name == normalized))
        match = result.scalar_one_or_none()
        if match is not None:
            return match

    fallback_query = select(Category.name).where(Category.is_fallback.is_(True))
    fallback_result = await session.execute(fallback_query)
    return fallback_result.scalar_one()
