"""US4 Unit test: Recommendation router — auth guard."""

from unittest.mock import AsyncMock


def test_recommendation_match_401_without_token(client):
    resp = client.post(
        "/internal/recommendations/match",
        json={"user_id": 1, "query": "savings"},
    )
    assert resp.status_code == 401


def test_recommendation_match_200_with_token(client, auth_headers, monkeypatch):
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=AsyncMock(all=lambda: [(1, "Need savings", 0.9)]))
    mock_session.flush = AsyncMock()
    mock_session.add = lambda x: None

    async def _mock_session_gen():
        yield mock_session

    monkeypatch.setattr("app.features.recommendations.router.get_own_session", _mock_session_gen)

    resp = client.post(
        "/internal/recommendations/match",
        json={"user_id": 1, "query": "I need a savings account"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "matches" in data
