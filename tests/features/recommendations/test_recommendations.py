"""US4 Unit test: Recommendation service — mock match without real DB."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.recommendations.service import match


@pytest.mark.asyncio
async def test_match_returns_products(monkeypatch, mock_embedder):
    mock_row = (1, "Need savings", 0.92)
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    results = await match(
        session=mock_session, embed_fn=mock_embedder, user_id=10, query="I need savings"
    )

    assert len(results) >= 1
    assert results[0].product_id == 1
    assert results[0].similarity > 0.8
    assert mock_session.add.call_count >= 1


@pytest.mark.asyncio
async def test_match_empty_query_returns_empty():
    mock_session = MagicMock()
    results = await match(session=mock_session, user_id=10, query="  ")
    assert results == []


@pytest.mark.asyncio
async def test_match_below_threshold_filtered(monkeypatch):
    async def _mock_embed_low(texts):
        return [[0.0] * 768 for _ in texts]

    mock_result = MagicMock()
    mock_result.all.return_value = [(1, "Need savings", 0.2)]

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    results = await match(
        session=mock_session, embed_fn=_mock_embed_low, user_id=10, query="savings"
    )
    assert results == []
