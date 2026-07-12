"""Chat slice tests -- token auth and mock-mode SSE streaming."""

from fastapi.testclient import TestClient


def test_chat_without_token_returns_401(client: TestClient):
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c1",
            "user_id": 1,
            "message": "hi",
        },
    )
    assert response.status_code == 401


def test_chat_with_wrong_token_returns_401(client: TestClient):
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c1",
            "user_id": 1,
            "message": "hi",
        },
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_chat_with_correct_token_streams(client: TestClient, auth_headers: dict):
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c1",
            "user_id": 1,
            "message": "hi",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


def test_chat_mock_mode_yields_frames(client: TestClient, auth_headers: dict):
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c1",
            "user_id": 1,
            "message": "hi",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "data:" in body
    assert "[DONE]" in body
