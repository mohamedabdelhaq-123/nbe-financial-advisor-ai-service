"""US1 Unit test: Analysis agent — grounded data references."""

import uuid

import pytest

from app.features.chat.agents.analysis import analysis_node
from app.features.chat.schemas import Reference


@pytest.mark.asyncio
async def test_analysis_node_returns_references(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    transactions = [
        type(
            "Txn",
            (),
            {
                "id": f"t{i}",
                "amount": f"{50 + i * 20}.00",
                "merchant_raw": f"Store {i}",
                "category": "food",
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
