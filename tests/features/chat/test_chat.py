"""Chat slice tests -- token auth and mock-mode SSE streaming (new envelope)."""

import json

from fastapi.testclient import TestClient


def test_chat_without_token_returns_401(client: TestClient):
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c1",
            "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
            "message": "hi",
        },
    )
    assert response.status_code == 401


def test_chat_with_wrong_token_returns_401(client: TestClient):
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c1",
            "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
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
            "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
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
            "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
            "message": "hi",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text

    # FR-001/FR-004: the new {event, data} envelope.
    assert '{"event": "token", "data":' in body or '"event":"token","data":' in body
    assert body.count('"event": "done"') + body.count('"event":"done"') == 1

    # The legacy ad-hoc envelope shapes are gone (the widget discriminator's
    # "type" field is fine — only the top-level {"type": ...} envelope is banned).
    assert "[DONE]" not in body
    assert '"type": "token"' not in body
    assert '"type": "error"' not in body


def test_chat_mock_done_payload_shape(client: TestClient, auth_headers: dict):
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c1-mock-done",
            "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
            "message": "hi",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200

    done_payload = _extract_done_payload(response.text)
    # FR-003: no id field; FR-005/FR-008: widget/references slots always present.
    assert "id" not in done_payload
    assert done_payload["widget"] is None
    assert done_payload["references"] == []
    assert done_payload["content"]


def _extract_done_payload(body: str) -> dict:
    """Parse the single terminal ``done`` event's data object from the SSE body."""
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        if payload.get("event") == "done":
            return payload["data"]
    raise AssertionError("no done event in body")
