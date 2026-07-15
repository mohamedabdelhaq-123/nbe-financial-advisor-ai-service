"""US4 Unit test: Recommendation service — mock match without real DB."""

import uuid
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.recommendations.service import match

_USER_ID = uuid.UUID("70b8d118-9b58-45ab-a8ad-4af9ce9105df")
_PRODUCT_ID = uuid.UUID("5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f")

# Mimics a SQLAlchemy Row: supports both tuple-unpacking and attribute access
# for the labeled `score` column, matching how service.py reads real rows.
_Row = namedtuple("_Row", ["product_id", "statement_text", "score"])


@pytest.mark.asyncio
async def test_match_returns_products(monkeypatch):
    monkeypatch.setattr(
        "app.features.recommendations.service._fetch_product_titles",
        AsyncMock(return_value={_PRODUCT_ID: "Premium Savings Account"}),
    )

    mock_row = _Row(_PRODUCT_ID, "Need savings", 0.92)
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    results = await match(session=mock_session, user_id=_USER_ID, query="I need savings")

    assert len(results) >= 1
    assert results[0].product_id == _PRODUCT_ID
    assert results[0].product_name == "Premium Savings Account"
    assert results[0].similarity > 0.8
    assert mock_session.add.call_count >= 1


@pytest.mark.asyncio
async def test_match_backend_outage_falls_back_to_placeholder(monkeypatch):
    monkeypatch.setattr(
        "app.features.recommendations.service._fetch_product_titles",
        AsyncMock(return_value={}),
    )

    mock_row = _Row(_PRODUCT_ID, "Need savings", 0.92)
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    results = await match(session=mock_session, user_id=_USER_ID, query="I need savings")

    assert len(results) == 1
    assert results[0].product_name == "Product unavailable"


@pytest.mark.asyncio
async def test_match_empty_query_returns_empty():
    mock_session = MagicMock()
    results = await match(session=mock_session, user_id=_USER_ID, query="  ")
    assert results == []


@pytest.mark.asyncio
async def test_match_below_threshold_filtered(monkeypatch):
    async def _mock_embed_low(texts):
        return [[0.0] * 768 for _ in texts]

    mock_result = MagicMock()
    mock_result.all.return_value = [_Row(_PRODUCT_ID, "Need savings", 0.2)]

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    results = await match(
        session=mock_session, embed_fn=_mock_embed_low, user_id=_USER_ID, query="savings"
    )
    assert results == []
