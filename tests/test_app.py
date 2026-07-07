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

from app.main import app  # noqa: E402  — must come after env setup

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_true():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_chat_mock_mode_returns_reply_field():
    """In mock mode the response must have the same JSON shape as the real one."""
    response = client.post("/chat", json={"message": "hi"})
    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert "hi" in body["reply"]


def test_chat_mock_echoes_message():
    response = client.post("/chat", json={"message": "say hello in 3 words"})
    assert response.status_code == 200
    assert "say hello in 3 words" in response.json()["reply"]


def test_missing_api_key_raises_when_mock_disabled(monkeypatch):
    """Config must fail fast if USE_MOCK_LLM=false and no real key is set."""
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "__mock__")

    # Re-importing config triggers the startup guard
    import importlib

    import app.config as cfg

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        importlib.reload(cfg)
