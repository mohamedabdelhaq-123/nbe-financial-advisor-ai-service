"""US4 Unit test: Recommendation service — mock match without real DB."""

import uuid
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.recommendations.service import match

_USER_ID = uuid.UUID("70b8d118-9b58-45ab-a8ad-4af9ce9105df")
_PRODUCT_ID = uuid.UUID("5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f")
_SECOND_PRODUCT_ID = uuid.UUID("d9b2ce52-94bb-474f-acbd-2c29e37e1284")
_THIRD_PRODUCT_ID = uuid.UUID("949c6ec6-cc2a-4671-a605-8a278272587c")

# Mimics a SQLAlchemy Row: supports both tuple-unpacking and attribute access
# for the labeled `score` column, matching how service.py reads real rows.
_Row = namedtuple("_Row", ["product_id", "statement_text", "score"])


@pytest.fixture(autouse=True)
def _already_synchronized_catalogue(monkeypatch):
    """Service matching tests focus on ranking; synchronization has its own suite."""

    monkeypatch.setattr(
        "app.features.recommendations.service.sync_problem_statements",
        AsyncMock(),
    )


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


@pytest.mark.asyncio
async def test_match_omits_products_far_below_the_best_result(monkeypatch):
    monkeypatch.setattr(
        "app.features.recommendations.service._fetch_product_titles",
        AsyncMock(
            return_value={
                _PRODUCT_ID: "Best match",
                _SECOND_PRODUCT_ID: "Comparable match",
            }
        ),
    )
    mock_result = MagicMock()
    mock_result.all.return_value = [
        _Row(_PRODUCT_ID, "Best", 0.80),
        _Row(_SECOND_PRODUCT_ID, "Comparable", 0.71),
        _Row(_THIRD_PRODUCT_ID, "Weak", 0.69),
    ]
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    results = await match(session=mock_session, user_id=_USER_ID, query="compare products")

    assert [result.product_id for result in results] == [_PRODUCT_ID, _SECOND_PRODUCT_ID]
