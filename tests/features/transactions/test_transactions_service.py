"""US1/US2/US3/Polish integration tests: transaction embedding service — embed_transactions()."""

import json
import uuid
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.backend_db.models import TRANSACTION_EMBEDDING_DIM, Transaction


def _uuid(s: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, s)


async def _insert_transaction(
    session,
    tid: uuid.UUID,
    *,
    merchant_raw: str = "Test Merchant",
    merchant_normalized: str | None = None,
    category: str = "food",
    amount: float = 42.50,
) -> None:
    await session.execute(
        text(
            "INSERT INTO transactions "
            "(id, user_id, account_id, transaction_date, amount, currency, "
            "merchant_raw, merchant_normalized, category_id, transaction_type) "
            "VALUES (:id, :uid, :aid, :dt, :amt, :cur, :mr, :mn, "
            "(SELECT id FROM categories WHERE name = :cat), :t)"
        ),
        {
            "id": tid,
            "uid": uuid.uuid4(),
            "aid": uuid.uuid4(),
            "dt": date(2026, 1, 15),
            "amt": amount,
            "cur": "EGP",
            "mr": merchant_raw,
            "mn": merchant_normalized,
            "cat": category,
            "t": "debit",
        },
    )


async def _raising_embed_fn(texts, dimensions=None):
    raise RuntimeError("provider unreachable")


async def _fetch(own_pg, tid: uuid.UUID) -> Transaction:
    async with own_pg() as session:
        result = await session.execute(
            select(Transaction)
            .where(Transaction.id == tid)
            .options(selectinload(Transaction.category))
        )
        return result.scalar_one()


@pytest.mark.asyncio
async def test_embed_new_transactions_populates_embedding(own_pg):
    from app.features.transactions.service import embed_transactions

    t1, t2 = _uuid("us1-a"), _uuid("us1-b")
    async with own_pg() as session:
        await _insert_transaction(session, t1, merchant_raw="Starbucks", category="food")
        await _insert_transaction(session, t2, merchant_raw="Uber", category="transport")
        await session.commit()

    embedded = await embed_transactions(
        session_gen=own_pg, own_session_gen=own_pg, transaction_ids=[t1, t2]
    )
    assert set(embedded) == {t1, t2}

    for tid in (t1, t2):
        row = await _fetch(own_pg, tid)
        assert row.embedding is not None
        assert len(row.embedding) == TRANSACTION_EMBEDDING_DIM


@pytest.mark.asyncio
async def test_embed_single_transaction_succeeds(own_pg):
    from app.features.transactions.service import embed_transactions

    t1 = _uuid("us1-single")
    async with own_pg() as session:
        await _insert_transaction(session, t1)
        await session.commit()

    embedded = await embed_transactions(
        session_gen=own_pg, own_session_gen=own_pg, transaction_ids=[t1]
    )
    assert embedded == [t1]
    assert (await _fetch(own_pg, t1)).embedding is not None


@pytest.mark.asyncio
async def test_reembed_overwrites_existing_embedding(own_pg):
    from app.features.transactions.service import embed_transactions

    t1 = _uuid("us2-reembed")
    async with own_pg() as session:
        await _insert_transaction(session, t1, merchant_raw="Original Merchant")
        await session.commit()

    await embed_transactions(session_gen=own_pg, own_session_gen=own_pg, transaction_ids=[t1])
    first_embedding = (await _fetch(own_pg, t1)).embedding
    assert first_embedding is not None

    async with own_pg() as session:
        result = await session.execute(select(Transaction).where(Transaction.id == t1))
        txn = result.scalar_one()
        txn.merchant_raw = "Corrected Merchant"
        await session.commit()

    await embed_transactions(session_gen=own_pg, own_session_gen=own_pg, transaction_ids=[t1])
    second_embedding = (await _fetch(own_pg, t1)).embedding
    assert second_embedding is not None
    assert second_embedding != first_embedding


@pytest.mark.asyncio
async def test_invalid_batch_writes_nothing(own_pg):
    from app.features.transactions.service import TransactionsNotFoundError, embed_transactions

    existing = _uuid("us3-existing")
    missing = _uuid("us3-missing")
    async with own_pg() as session:
        await _insert_transaction(session, existing)
        await session.commit()

    with pytest.raises(TransactionsNotFoundError) as exc_info:
        await embed_transactions(
            session_gen=own_pg, own_session_gen=own_pg, transaction_ids=[existing, missing]
        )

    assert exc_info.value.invalid_transaction_ids == [missing]
    assert (await _fetch(own_pg, existing)).embedding is None


@pytest.mark.asyncio
async def test_provider_failure_leaves_no_partial_writes(own_pg):
    from app.features.transactions.service import embed_transactions

    t1, t2 = _uuid("us3-fail-a"), _uuid("us3-fail-b")
    async with own_pg() as session:
        await _insert_transaction(session, t1)
        await _insert_transaction(session, t2)
        await session.commit()

    with pytest.raises(RuntimeError, match="provider unreachable"):
        await embed_transactions(
            session_gen=own_pg,
            own_session_gen=own_pg,
            transaction_ids=[t1, t2],
            embed_fn=_raising_embed_fn,
        )

    assert (await _fetch(own_pg, t1)).embedding is None
    assert (await _fetch(own_pg, t2)).embedding is None


@pytest.mark.asyncio
async def test_audit_log_written_once_per_successful_request(own_pg):
    from app.features.audit.models import AiAuditLog
    from app.features.transactions.service import embed_transactions

    # The Testcontainers Postgres is session-scoped (tests/conftest.py's own_db_url), so
    # ai_audit_log accumulates rows across every test in this module/run — filter down to
    # rows naming exactly this test's (unique) transaction ID rather than asserting a bare
    # total count.
    t1 = _uuid("polish-audit-success")
    async with own_pg() as session:
        await _insert_transaction(session, t1)
        await session.commit()

    await embed_transactions(session_gen=own_pg, own_session_gen=own_pg, transaction_ids=[t1])

    async with own_pg() as session:
        rows = (
            (
                await session.execute(
                    select(AiAuditLog).where(AiAuditLog.action == "transactions.embed")
                )
            )
            .scalars()
            .all()
        )
    matching = [r for r in rows if json.loads(r.detail_json)["transaction_ids"] == [str(t1)]]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_no_audit_row_on_failed_request(own_pg):
    from app.features.audit.models import AiAuditLog
    from app.features.transactions.service import TransactionsNotFoundError, embed_transactions

    async with own_pg() as session:
        before = (
            (
                await session.execute(
                    select(AiAuditLog).where(AiAuditLog.action == "transactions.embed")
                )
            )
            .scalars()
            .all()
        )
    before_count = len(before)

    with pytest.raises(TransactionsNotFoundError):
        await embed_transactions(
            session_gen=own_pg,
            own_session_gen=own_pg,
            transaction_ids=[_uuid("polish-audit-missing")],
        )

    async with own_pg() as session:
        after = (
            (
                await session.execute(
                    select(AiAuditLog).where(AiAuditLog.action == "transactions.embed")
                )
            )
            .scalars()
            .all()
        )
    assert len(after) == before_count


@pytest.mark.asyncio
async def test_only_embedding_column_changes_on_success(own_pg):
    from app.features.transactions.service import embed_transactions

    t1 = _uuid("polish-no-collateral")
    async with own_pg() as session:
        await _insert_transaction(
            session, t1, merchant_raw="Collateral Co", category="lifestyle", amount=99.99
        )
        await session.commit()

    before = await _fetch(own_pg, t1)
    before_snapshot = {
        "transaction_date": before.transaction_date,
        "amount": before.amount,
        "currency": before.currency,
        "merchant_raw": before.merchant_raw,
        "merchant_normalized": before.merchant_normalized,
        "category": before.category.name if before.category else None,
        "user_id": before.user_id,
        "account_id": before.account_id,
    }

    await embed_transactions(session_gen=own_pg, own_session_gen=own_pg, transaction_ids=[t1])

    after = await _fetch(own_pg, t1)
    assert after.embedding is not None
    after_snapshot = {
        "transaction_date": after.transaction_date,
        "amount": after.amount,
        "currency": after.currency,
        "merchant_raw": after.merchant_raw,
        "merchant_normalized": after.merchant_normalized,
        "category": after.category.name if after.category else None,
        "user_id": after.user_id,
        "account_id": after.account_id,
    }
    assert after_snapshot == before_snapshot


@pytest.mark.asyncio
async def test_no_collateral_changes_on_rejected_batch(own_pg):
    from app.features.transactions.service import TransactionsNotFoundError, embed_transactions

    existing = _uuid("polish-no-collateral-reject")
    async with own_pg() as session:
        await _insert_transaction(session, existing, merchant_raw="Untouched Co")
        await session.commit()

    before = await _fetch(own_pg, existing)

    with pytest.raises(TransactionsNotFoundError):
        await embed_transactions(
            session_gen=own_pg,
            own_session_gen=own_pg,
            transaction_ids=[existing, _uuid("polish-no-collateral-missing")],
        )

    after = await _fetch(own_pg, existing)
    assert after.embedding is None
    assert after.merchant_raw == before.merchant_raw
    assert after.amount == before.amount
