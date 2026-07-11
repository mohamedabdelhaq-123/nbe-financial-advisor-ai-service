"""US2 Unit test: Anomaly detection."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text


def _uuid(s: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, s)


@pytest.mark.asyncio
async def test_detect_anomaly_flags_outlier(own_pg):
    from app.features.analytics.jobs.anomaly_detection import detect_anomalies

    uid = _uuid("4")
    aid = _uuid("a4")

    async with own_pg() as session:
        amounts = [15.00, 18.00, 22.00, 20.00, 25.00, 17.00, 21.00]
        for i, amt in enumerate(amounts, start=1):
            await session.execute(
                text(
                    "INSERT INTO transactions "
                    "(id, user_id, account_id, transaction_date, amount, "
                    "merchant_raw, category, transaction_type) "
                    "VALUES (:id, :uid, :aid, :dt, :amt, :m, :c, :t)"
                ),
                {
                    "id": _uuid(f"a{i}"),
                    "uid": uid,
                    "aid": aid,
                    "dt": date(2026, 3, 14 + i),
                    "amt": amt,
                    "m": f"Food Place {i}",
                    "c": "food",
                    "t": "debit",
                },
            )
        await session.execute(
            text(
                "INSERT INTO transactions "
                "(id, user_id, account_id, transaction_date, amount, "
                "merchant_raw, category, transaction_type) "
                "VALUES (:id, :uid, :aid, :dt, :amt, :m, :c, :t)"
            ),
            {
                "id": _uuid("a99"),
                "uid": uid,
                "aid": aid,
                "dt": date(2026, 3, 20),
                "amt": 500.00,
                "m": "Luxury Meal",
                "c": "food",
                "t": "debit",
            },
        )
        await session.commit()

    flags = await detect_anomalies(
        session_gen=own_pg,
        user_id=str(uid),
        account_id=str(aid),
        month="2026-03",
    )
    food_flags = [f for f in flags if f.category == "food"]
    assert len(food_flags) >= 1
    assert any(abs(f.amount - 500.0) < 0.01 for f in food_flags)
