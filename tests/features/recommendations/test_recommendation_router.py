"""US4 Unit test: Recommendation router — auth guard."""

from collections import namedtuple
from unittest.mock import AsyncMock

_USER_ID = "70b8d118-9b58-45ab-a8ad-4af9ce9105df"
_PRODUCT_ID = "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f"
_Row = namedtuple("_Row", ["product_id", "statement_text", "score"])


def test_recommendation_match_401_without_token(client):
    resp = client.post(
        "/internal/recommendations/match",
        json={"user_id": _USER_ID, "query": "savings"},
    )
    assert resp.status_code == 401


def test_recommendation_match_200_with_token(client, auth_headers, monkeypatch):
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=AsyncMock(all=lambda: [_Row(_PRODUCT_ID, "Need savings", 0.9)])
    )
    mock_session.flush = AsyncMock()
    mock_session.add = lambda x: None

    async def _mock_session_gen():
        yield mock_session

    monkeypatch.setattr("app.features.recommendations.router.get_own_session", _mock_session_gen)

    resp = client.post(
        "/internal/recommendations/match",
        json={"user_id": _USER_ID, "query": "I need a savings account"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "matches" in data
