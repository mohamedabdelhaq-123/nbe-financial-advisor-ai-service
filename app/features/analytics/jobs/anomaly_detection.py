"""Anomaly detection — per-category statistical outlier detection."""

import uuid
from collections import defaultdict

import numpy as np
from sqlalchemy import select

from app.backend_db.models import Transaction
from app.features.analytics.schemas import AnomalyFlagResult


async def detect_anomalies(
    session_gen,
    user_id: str = "",
    account_id: str = "",
    month: str = "",
) -> list[AnomalyFlagResult]:
    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    aid = uuid.UUID(account_id) if isinstance(account_id, str) else account_id

    async with session_gen() as session:
        result = await session.execute(
            select(Transaction).where(
                Transaction.user_id == uid,
                Transaction.account_id == aid,
            )
        )
        transactions = result.scalars().all()

    by_category: dict[str, list[float]] = defaultdict(list)
    month_outliers: dict[str, float] = defaultdict(float)

    for txn in transactions:
        amt = float(getattr(txn, "amount", 0) or 0)
        cat = getattr(txn, "category", "uncategorized") or "uncategorized"
        txn_type = getattr(txn, "transaction_type", "debit") or "debit"
        if txn_type == "credit":
            continue

        d = getattr(txn, "transaction_date", None)
        txn_month = ""
        if d is not None:
            if isinstance(d, str):
                txn_month = d[:7]
            elif hasattr(d, "strftime"):
                txn_month = d.strftime("%Y-%m")

        by_category[cat].append(amt)
        if txn_month == month:
            month_outliers[cat] += amt

    flags: list[AnomalyFlagResult] = []
    for cat, values in by_category.items():
        arr = np.array(values)
        if len(arr) < 3:
            continue

        q1 = np.percentile(arr, 25)
        q3 = np.percentile(arr, 75)
        iqr = q3 - q1
        if iqr == 0:
            continue

        upper_bound = q3 + 1.5 * iqr

        if cat in month_outliers and month_outliers[cat] > upper_bound:
            flags.append(
                AnomalyFlagResult(
                    user_id=str(uid),
                    account_id=str(aid),
                    category=cat,
                    month=month,
                    amount=month_outliers[cat],
                    reason=(
                        f"Spend of {month_outliers[cat]:.2f} in '{cat}' "
                        f"exceeds IQR upper bound ({upper_bound:.2f})"
                    ),
                )
            )

    return flags
