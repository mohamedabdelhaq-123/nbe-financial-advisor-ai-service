"""Category resolution against the backend-owned category taxonomy.

The category list itself lives in the backend's `categories` table (Django-
migrated, income/expense-typed) and is read here through the existing
read-only mirror — this service no longer owns a copy of its own.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend_db.models import Category


async def resolve_category(
    backend_session: AsyncSession, raw: str | None, transaction_type: str | None = None
) -> str:
    """Resolve a raw (possibly LLM-produced) category string to a known category name.

    Case-insensitive exact match against `Category.name`; falls back to the
    `is_fallback` row for the resolved direction when `raw` is missing or
    matches nothing — `transaction_type == "credit"` resolves to the income
    fallback, anything else to the expense one, so an unresolved category on a
    credit transaction doesn't silently land under an expense-labeled bucket.
    """
    if raw:
        normalized = raw.strip().lower()
        result = await backend_session.execute(
            select(Category.name).where(Category.name == normalized)
        )
        match = result.scalar_one_or_none()
        if match is not None:
            return match

    is_income = (transaction_type or "").strip().lower() == "credit"
    fallback_query = select(Category.name).where(
        Category.is_fallback.is_(True),
        Category.category_type == ("income" if is_income else "expense"),
    )
    fallback_result = await backend_session.execute(fallback_query)
    return fallback_result.scalar_one()
