"""US1 Unit test: Analysis agent — grounded data references."""

import uuid

import pytest

from app.features.chat.agents.analysis import analysis_node
from app.features.chat.schemas import Reference


@pytest.mark.asyncio
async def test_analysis_node_returns_references(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    transactions = [
        type(
            "Txn",
            (),
            {
                "id": f"t{i}",
                "amount": f"{50 + i * 20}.00",
                "merchant_raw": f"Store {i}",
                # `category` is a relationship on the real model — resolves to an
                # object with `.name`, not a bare string. See analysis_node's
                # `txn.category.name if txn.category else "uncategorized"`.
                "category": SimpleNamespace(name="food"),
            },
        )()
        for i in range(1, 4)
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = transactions

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.close = AsyncMock()

    async def _mock_gen():
        yield mock_session

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    state = {
        "messages": [],
        "user_id": uuid.UUID("70b8d118-9b58-45ab-a8ad-4af9ce9105df"),
        "user_context": None,
        "intent": "analysis",
    }

    result = await analysis_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0

    # FR-006/FR-007: every reference is a typed Reference with target_type == "transaction".
    refs = result["message_references"]
    assert len(refs) == len(transactions)
    assert all(isinstance(r, Reference) for r in refs)
    assert all(r.target_type == "transaction" for r in refs)
    assert all(r.target_id == str(txn.id) for r, txn in zip(refs, transactions, strict=True))


class _ResolvedCategory:
    """Stands in for the real `Categories` row `Transaction.category` resolves to."""

    def __init__(self, name: str):
        self.name = name


class _LazyCategoryTxn:
    """Mimics a real SQLAlchemy `Transactions` row where `category` is a
    relationship, not a plain column: accessing it raises once the owning
    session has closed — the same failure mode as SQLAlchemy's lazy loader
    under AsyncSession (DetachedInstanceError, or MissingGreenlet if the
    load is attempted outside a greenlet context at all)."""

    def __init__(self, id_: str, amount: str, merchant_raw: str, session_state: dict):
        self.id = id_
        self.amount = amount
        self.merchant_raw = merchant_raw
        self._session_state = session_state

    @property
    def category(self):
        if self._session_state["closed"]:
            raise RuntimeError("simulated: relationship access outside the session")
        return _ResolvedCategory("food")


@pytest.mark.asyncio
async def test_analysis_node_reads_lazy_attributes_before_session_closes(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    # Regression test: analysis_node used to build `lines`/`references` *after*
    # the `async for session in get_backend_session()` block, so touching a
    # lazy-loaded attribute (like the real `category` relationship) there hit
    # DetachedInstanceError — silently swallowed into "Backend is unavailable".
    session_state = {"closed": False}
    transactions = [
        _LazyCategoryTxn(f"t{i}", f"{50 + i * 20}.00", f"Store {i}", session_state)
        for i in range(1, 4)
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = transactions

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _mock_gen():
        try:
            yield mock_session
        finally:
            session_state["closed"] = True

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    state = {
        "messages": [],
        "user_id": uuid.UUID("70b8d118-9b58-45ab-a8ad-4af9ce9105df"),
        "user_context": None,
        "intent": "analysis",
    }

    result = await analysis_node(state)

    # A regression would fall into the except-Exception branch and return
    # this text instead.
    assert "Backend is unavailable" not in result["messages"][0].content
    assert len(result["message_references"]) == len(transactions)

    # The analysis agent reports what the user already spent — a statement of
    # fact, not advice — so it must NOT carry the advice disclaimer. That is
    # reserved for the planner and the recommendation agent (guards.py's
    # with_disclaimer docstring).
    from app.features.chat.guards import DISCLAIMER

    assert DISCLAIMER not in result["messages"][0].content


@pytest.mark.asyncio
async def test_analysis_node_no_data(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.close = AsyncMock()

    async def _mock_gen():
        yield mock_session

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    state = {
        "messages": [],
        "user_id": uuid.UUID("35949f20-c6b5-4889-a37d-a09ef0af6b1e"),
        "user_context": None,
        "intent": "analysis",
    }

    result = await analysis_node(state)
    assert "messages" in result
    no_data_found = any(
        "don't have" in m.content.lower() or "no data" in m.content.lower()
        for m in result["messages"]
    )
    assert no_data_found
