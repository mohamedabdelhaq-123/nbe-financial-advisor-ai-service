"""Recurring charge detection — deterministic frequency analysis."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from app.backend_db.models import Transaction
from app.features.analytics.schemas import RecurringChargeResult


async def detect_recurring_charges(
    session_gen,
    user_id: str = "",
    account_id: str = "",
) -> list[RecurringChargeResult]:
    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    aid = uuid.UUID(account_id) if isinstance(account_id, str) else account_id

    async with session_gen() as session:
        result = await session.execute(
            select(Transaction)
            .where(
                Transaction.user_id == uid,
                Transaction.account_id == aid,
            )
            .order_by(Transaction.transaction_date)
        )
        transactions = result.scalars().all()

    groups: dict[str, list] = defaultdict(list)
    for txn in transactions:
        merchant = (getattr(txn, "merchant_raw", "") or "").strip().lower()
        amt = float(getattr(txn, "amount", 0) or 0)
        key = f"{merchant}|{amt:.2f}"
        groups[key].append(txn)

    recurring: list[RecurringChargeResult] = []
    for key, txns in groups.items():
        if len(txns) < 3:
            continue
        merchant, amt_str = key.rsplit("|", 1)
        dates = []
        for t in txns:
            d = getattr(t, "transaction_date", None)
            if d is not None:
                if isinstance(d, str):
                    dates.append(datetime.strptime(d, "%Y-%m-%d"))
                elif hasattr(d, "strftime"):
                    dates.append(d)

        if len(dates) < 2:
            continue

        gaps = []
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            if gap > 0:
                gaps.append(gap)

        if not gaps:
            continue

        avg_gap = sum(gaps) / len(gaps)
        if all(abs(g - avg_gap) <= 5 for g in gaps) and avg_gap <= 35:
            recurring.append(
                RecurringChargeResult(
                    user_id=str(uid),
                    account_id=str(aid),
                    merchant=merchant.title(),
                    amount=float(amt_str),
                    cadence_days=round(avg_gap),
                )
            )

    return recurring
