"""
Deterministic tests for the AI service.
Run entirely in mock mode (USE_MOCK_LLM=1) — no API key required.
"""

import os

import pytest
from fastapi.testclient import TestClient

# Force mock mode before the app module is imported
os.environ.setdefault("USE_MOCK_LLM", "1")
os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("OPENAI_API_KEY", "__mock__")
os.environ.setdefault("MODEL_NAME", "gpt-4o-mini")
os.environ.setdefault("AI_SERVICE_TOKEN", "test-token-for-ci")

from app.main import app  # noqa: E402  — must come after env setup

_TOKEN = os.environ["AI_SERVICE_TOKEN"]
client = TestClient(app)


# ── probe tests ───────────────────────────────────────────────────────────────


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_token():
    """Health probe must work without any auth header — used by Docker HEALTHCHECK."""
    response = client.get("/health")
    assert response.status_code == 200


def test_ready_returns_true():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


# ── token auth tests ──────────────────────────────────────────────────────────


def test_chat_without_token_returns_401():
    response = client.post("/chat", json={"message": "hi"})
    assert response.status_code == 401


def test_chat_with_wrong_token_returns_401():
    response = client.post(
        "/chat",
        json={"message": "hi"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_chat_with_correct_token_returns_200():
    response = client.post(
        "/chat",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == 200
    assert "reply" in response.json()


# ── mock mode tests ───────────────────────────────────────────────────────────


def test_chat_mock_mode_returns_reply_field():
    """In mock mode the response must have the same JSON shape as the real one."""
    response = client.post(
        "/chat",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert "hi" in body["reply"]


def test_chat_mock_echoes_message():
    response = client.post(
        "/chat",
        json={"message": "say hello in 3 words"},
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == 200
    assert "say hello in 3 words" in response.json()["reply"]


# ── fail-fast config test ─────────────────────────────────────────────────────


def test_missing_api_key_raises_when_mock_disabled(monkeypatch):
    """Config must fail fast if USE_MOCK_LLM=false and no real key is set."""
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "__mock__")

    import importlib

    import app.config as cfg

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        importlib.reload(cfg)
