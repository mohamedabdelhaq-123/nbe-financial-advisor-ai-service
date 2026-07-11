"""US1 Unit test: Analysis agent — grounded data references."""

import pytest

from app.features.chat.agents.analysis import analysis_node


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
        "user_context": {"user_id": "10"},
        "intent": "analysis",
    }

    result = await analysis_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0
    assert "message_references" in result
    assert len(result["message_references"]) > 0


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
        "user_context": {"user_id": "99"},
        "intent": "analysis",
    }

    result = await analysis_node(state)
    assert "messages" in result
    no_data_found = any(
        "don't have" in m.content.lower() or "no data" in m.content.lower()
        for m in result["messages"]
    )
    assert no_data_found
