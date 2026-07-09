"""Liveness/readiness probe tests — must work without any auth."""

from fastapi.testclient import TestClient


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
