"""US5 Auth matrix — every /internal/* endpoint requires a token."""

import pytest

AUTH_ENDPOINTS = [
    ("POST", "/internal/chat"),
    ("POST", "/internal/plan/question"),
    ("POST", "/internal/plan/generate"),
    ("POST", "/internal/recommendations/match"),
    ("POST", "/internal/analyze/post-ingestion"),
    ("POST", "/internal/analyze/monthly-summary"),
    ("POST", "/internal/analyze/anomaly-check"),
]

PUBLIC_ENDPOINTS = [
    ("GET", "/health"),
    ("GET", "/ready"),
]


@pytest.mark.parametrize("method,path", AUTH_ENDPOINTS)
def test_internal_endpoints_401_without_token(client, method, path):
    resp = client.post(path, json={"user_id": 1})
    assert resp.status_code == 401, f"{method} {path} should require auth"


@pytest.mark.parametrize("method,path", PUBLIC_ENDPOINTS)
def test_public_endpoints_accessible(client, method, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{method} {path} should be public"
