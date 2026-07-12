"""US2 Unit test: Monthly summary computation."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text


def _uuid(s: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, s)


@pytest.mark.asyncio
async def test_monthly_summary_computes_totals(own_pg, mock_embedder):
    from app.features.analytics.jobs.monthly_summary import compute_monthly_summary

    uid = _uuid("1")
    aid = _uuid("a1")

    async with own_pg() as session:
        rows = [
            ("t1", date(2026, 1, 15), 50.00, "Grocery", "food", "debit"),
            ("t2", date(2026, 1, 16), 30.00, "Gas Station", "transport", "debit"),
            ("t3", date(2026, 1, 17), 200.00, "Salary", "income", "credit"),
        ]
        for rid, dt, amt, merchant, cat, ttype in rows:
            await session.execute(
                text(
                    "INSERT INTO transactions "
                    "(id, user_id, account_id, transaction_date, amount, "
                    "merchant_raw, category, transaction_type) "
                    "VALUES (:id, :uid, :aid, :dt, :amt, :m, :c, :t)"
                ),
                {
                    "id": _uuid(rid),
                    "uid": uid,
                    "aid": aid,
                    "dt": dt,
                    "amt": amt,
                    "m": merchant,
                    "c": cat,
                    "t": ttype,
                },
            )
        await session.commit()

    result = await compute_monthly_summary(
        session_gen=own_pg,
        embed_fn=mock_embedder,
        user_id=str(uid),
        account_id=str(aid),
        month="2026-01",
    )
    assert result.total_expense == pytest.approx(80.0)
    assert result.total_income == pytest.approx(200.0)
    assert result.net == pytest.approx(120.0)
    assert "food" in result.by_category
    assert len(result.embedding) == 768


@pytest.mark.asyncio
async def test_monthly_summary_idempotent(own_pg, mock_embedder):
    from app.features.analytics.jobs.monthly_summary import compute_monthly_summary

    uid = _uuid("2")
    aid = _uuid("a2")

    async with own_pg() as session:
        await session.execute(
            text(
                "INSERT INTO transactions "
                "(id, user_id, account_id, transaction_date, amount, "
                "merchant_raw, category, transaction_type) "
                "VALUES (:id, :uid, :aid, :dt, :amt, :m, :c, :t)"
            ),
            {
                "id": _uuid("t10"),
                "uid": uid,
                "aid": aid,
                "dt": date(2026, 2, 1),
                "amt": 100.00,
                "m": "Rent",
                "c": "housing",
                "t": "debit",
            },
        )
        await session.commit()

    r1 = await compute_monthly_summary(
        session_gen=own_pg,
        embed_fn=mock_embedder,
        user_id=str(uid),
        account_id=str(aid),
        month="2026-02",
    )
    r2 = await compute_monthly_summary(
        session_gen=own_pg,
        embed_fn=mock_embedder,
        user_id=str(uid),
        account_id=str(aid),
        month="2026-02",
    )
    assert r1.total_expense == r2.total_expense
    assert r1.embedding == r2.embedding
