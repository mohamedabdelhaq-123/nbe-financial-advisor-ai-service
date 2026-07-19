"""Liveness/readiness probe tests — must work without any auth."""

from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_returns_ok(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_token(client: TestClient):
    """Health probe must work without auth — used by the Docker HEALTHCHECK."""
    response = client.get("/health")
    assert response.status_code == 200


def test_ready_returns_true(client: TestClient):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_mineru_health_mock_mode(client: TestClient, monkeypatch):
    """Mock mode reports ready with no network call."""
    monkeypatch.setattr(settings, "use_mock_mineru", True)
    response = client.get("/health/mineru")
    assert response.status_code == 200
    assert response.json() == {"mode": "mock", "ready": True}


def test_mineru_health_real_unreachable(client: TestClient, monkeypatch):
    """Real mode against a dead endpoint reports not-ready with a detail,
    rather than raising — the whole point of the probe."""
    monkeypatch.setattr(settings, "use_mock_mineru", False)
    monkeypatch.setattr(settings, "mineru_api_url", "http://127.0.0.1:1")
    response = client.get("/health/mineru")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "real"
    assert body["ready"] is False
    assert "detail" in body


def test_mineru_health_needs_no_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "use_mock_mineru", True)
    assert client.get("/health/mineru").status_code == 200
