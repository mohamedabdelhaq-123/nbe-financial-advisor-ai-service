"""Monthly summary computation — deterministic SQL aggregation."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.backend_db.models import MONTHLY_SUMMARY_EMBEDDING_DIM, Transaction
from app.features.analytics.schemas import MonthlySummaryResult


async def compute_monthly_summary(
    session_gen,
    embed_fn=None,
    user_id: str = "",
    account_id: str = "",
    month: str = "",
) -> MonthlySummaryResult:
    if embed_fn is None:
        from app.features.embed.service import embed_texts

        embed_fn = embed_texts

    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    aid = uuid.UUID(account_id) if isinstance(account_id, str) else account_id

    async with session_gen() as session:
        base = (
            select(Transaction)
            .where(
                Transaction.user_id == uid,
                Transaction.account_id == aid,
                func.to_char(Transaction.transaction_date, "YYYY-MM") == month,
            )
            .options(selectinload(Transaction.category))
        )
        result = await session.execute(base)
        transactions = result.scalars().all()

    total_income = 0.0
    total_expense = 0.0
    by_category: dict[str, float] = {}

    for txn in transactions:
        amt = float(getattr(txn, "amount", 0) or 0)
        cat = txn.category.name if txn.category else "uncategorized"
        txn_type = getattr(txn, "transaction_type", "debit") or "debit"

        if txn_type == "credit":
            total_income += amt
        else:
            total_expense += amt
            by_category[cat] = by_category.get(cat, 0.0) + amt

    net = total_income - total_expense

    summary_text = (
        f"Monthly summary for {month}: "
        f"income={total_income:.2f}, expense={total_expense:.2f}, "
        f"categories={by_category}"
    )
    vectors = await embed_fn([summary_text], dimensions=MONTHLY_SUMMARY_EMBEDDING_DIM)
    embedding = vectors[0] if vectors else []

    return MonthlySummaryResult(
        user_id=str(uid),
        account_id=str(aid),
        month=month,
        total_income=total_income,
        total_expense=total_expense,
        net=net,
        by_category=by_category,
        embedding=embedding,
    )
