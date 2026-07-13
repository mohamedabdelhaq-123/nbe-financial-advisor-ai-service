"""Deterministic duplicate matching against the user's existing transactions."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_DUPLICATE_WINDOW_DAYS = 2


async def find_duplicate(
    session: AsyncSession,
    user_id: uuid.UUID,
    transaction_date: date,
    amount: Decimal,
) -> str | None:
    """Return the id of the closest likely-duplicate existing transaction, or None.

    Matches on exact amount and a `transaction_date` within
    `_DUPLICATE_WINDOW_DAYS`, scoped by user (not account — may not be linked
    yet, research.md §4). Only the minimal columns needed are selected, per
    Constitution III's egress-minimization clause.
    """
    from app.backend_db.models import Transaction

    window_start = transaction_date - timedelta(days=_DUPLICATE_WINDOW_DAYS)
    window_end = transaction_date + timedelta(days=_DUPLICATE_WINDOW_DAYS)

    result = await session.execute(
        select(Transaction.id, Transaction.transaction_date).where(
            Transaction.user_id == user_id,
            Transaction.amount == amount,
            Transaction.transaction_date >= window_start,
            Transaction.transaction_date <= window_end,
        )
    )
    rows = result.all()
    if not rows:
        return None

    closest = min(rows, key=lambda row: abs((row.transaction_date - transaction_date).days))
    return str(closest.id)
