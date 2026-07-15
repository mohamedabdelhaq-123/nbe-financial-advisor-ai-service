"""Transaction embedding service — fetch, summarize, embed, and persist atomically.

Writes to `transactions.embedding` are a Constitution-authorized, narrowly scoped
exception to this service's otherwise read-only backend DB access (Principle IV).
The `ai_readonly` role's `default_transaction_read_only = on` default means every
write transaction MUST issue `SET TRANSACTION READ WRITE` as its first statement —
before any query, per Postgres semantics — or the subsequent UPDATE fails despite
the column-level GRANT already in place (see specs/008-embed-transactions/research.md).
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.backend_db.models import TRANSACTION_EMBEDDING_DIM, Transaction
from app.core.audit import record_audit


class TransactionsNotFoundError(Exception):
    """Raised when one or more requested transaction IDs don't exist.

    Nothing is written for the whole request in this case (all-or-nothing, FR-006).
    """

    def __init__(self, invalid_transaction_ids: list[uuid.UUID]):
        self.invalid_transaction_ids = invalid_transaction_ids
        super().__init__(f"Transaction IDs not found: {invalid_transaction_ids}")


def _build_summary_text(transaction: Transaction) -> str:
    merchant = transaction.merchant_normalized or transaction.merchant_raw or ""
    category = transaction.category.name if transaction.category else ""
    return (
        f"{merchant}, {category}, {transaction.amount} {transaction.currency}, "
        f"{transaction.transaction_date}"
    )


async def embed_transactions(
    session_gen,
    own_session_gen,
    transaction_ids: list[uuid.UUID],
    embed_fn=None,
) -> list[uuid.UUID]:
    if embed_fn is None:
        from app.features.embed.service import embed_texts

        embed_fn = embed_texts

    async with session_gen() as session:
        # Must be the transaction's first statement (before the SELECT below) —
        # Postgres only allows changing READ WRITE/READ ONLY before any query runs.
        await session.execute(text("SET TRANSACTION READ WRITE"))

        result = await session.execute(
            select(Transaction)
            .where(Transaction.id.in_(transaction_ids))
            .options(selectinload(Transaction.category))
        )
        by_id = {t.id: t for t in result.scalars().all()}

        missing = [tid for tid in transaction_ids if tid not in by_id]
        if missing:
            raise TransactionsNotFoundError(missing)

        ordered = [by_id[tid] for tid in transaction_ids]
        summaries = [_build_summary_text(t) for t in ordered]
        vectors = await embed_fn(summaries, dimensions=TRANSACTION_EMBEDDING_DIM)

        for transaction, vector in zip(ordered, vectors, strict=True):
            transaction.embedding = vector

        await session.commit()

    async with own_session_gen() as own_session:
        await record_audit(
            own_session,
            user_id=None,
            action="transactions.embed",
            detail={"transaction_ids": [str(tid) for tid in transaction_ids]},
        )
        await own_session.commit()

    return list(transaction_ids)
