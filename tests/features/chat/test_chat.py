"""Chat slice tests — token auth and mock-mode response shape."""

from fastapi.testclient import TestClient


def test_chat_without_token_returns_401(client: TestClient):
    response = client.post("/chat", json={"message": "hi"})
    assert response.status_code == 401


def test_chat_with_wrong_token_returns_401(client: TestClient):
    response = client.post(
        "/chat",
        json={"message": "hi"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_chat_with_correct_token_returns_200(client: TestClient, auth_headers: dict):
    response = client.post("/chat", json={"message": "hi"}, headers=auth_headers)
    assert response.status_code == 200
    assert "reply" in response.json()


def test_chat_mock_mode_returns_reply_field(client: TestClient, auth_headers: dict):
    """In mock mode the response must have the same JSON shape as the real one."""
    response = client.post("/chat", json={"message": "hi"}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert "hi" in body["reply"]


def test_chat_mock_echoes_message(client: TestClient, auth_headers: dict):
    response = client.post(
        "/chat",
        json={"message": "say hello in 3 words"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "say hello in 3 words" in response.json()["reply"]
