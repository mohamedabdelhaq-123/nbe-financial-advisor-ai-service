"""
Shared test setup.

The whole suite runs in mock mode (USE_MOCK_LLM=1) — no API key, no model or
network calls. Environment must be set before the app is imported so config
validation and the mock short-circuit see it.
"""

import os

os.environ.setdefault("USE_MOCK_LLM", "1")
os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("OPENAI_API_KEY", "__mock__")
os.environ.setdefault("MODEL_NAME", "gpt-4o-mini")
os.environ.setdefault("AI_SERVICE_TOKEN", "test-token-for-ci")

import pytest
from fastapi.testclient import TestClient

from app.main import app

TOKEN = os.environ["AI_SERVICE_TOKEN"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
