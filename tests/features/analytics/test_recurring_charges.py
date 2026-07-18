"""US2 Unit test: Recurring charge detection."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text


def _uuid(s: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, s)


@pytest.mark.asyncio
async def test_detect_recurring_charges(own_pg):
    from app.features.analytics.jobs.recurring_charges import (
        detect_recurring_charges,
    )

    uid = _uuid("3")
    aid = _uuid("a3")

    async with own_pg() as session:
        for i, m in enumerate([1, 2, 3, 4], start=100):
            await session.execute(
                text(
                    "INSERT INTO transactions "
                    "(id, user_id, account_id, transaction_date, amount, "
                    "merchant_raw, category_id, transaction_type) "
                    "VALUES (:id, :uid, :aid, :dt, :amt, :m, "
                    "(SELECT id FROM categories WHERE name = :c), :t)"
                ),
                {
                    "id": _uuid(f"r{i}"),
                    "uid": uid,
                    "aid": aid,
                    "dt": date(2026, m, 5),
                    "amt": 29.99,
                    "m": "Netflix",
                    "c": "lifestyle",
                    "t": "debit",
                },
            )
        await session.execute(
            text(
                "INSERT INTO transactions "
                "(id, user_id, account_id, transaction_date, amount, "
                "merchant_raw, category_id, transaction_type) "
                "VALUES (:id, :uid, :aid, :dt, :amt, :m, "
                "(SELECT id FROM categories WHERE name = :c), :t)"
            ),
            {
                "id": _uuid("r200"),
                "uid": uid,
                "aid": aid,
                "dt": date(2026, 1, 10),
                "amt": 15.00,
                "m": "Coffee Shop",
                "c": "food",
                "t": "debit",
            },
        )
        await session.commit()

    results = await detect_recurring_charges(
        session_gen=own_pg,
        user_id=str(uid),
        account_id=str(aid),
    )
    assert len(results) >= 1
    names = {r.merchant for r in results}
    assert "Netflix" in names
    assert "Coffee Shop" not in names
