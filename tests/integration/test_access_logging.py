"""Integration tests: RequestLoggingMiddleware end-to-end over real HTTP
requests, capturing actual stdout (the real production path, not a
structlog-internal capture) via pytest's OS-level `capfd`.
"""

import json

from fastapi.testclient import TestClient


def _entries(capfd) -> list[dict]:
    out, _ = capfd.readouterr()
    return [json.loads(line) for line in out.strip().splitlines() if line]


def test_completed_request_emits_one_access_log_entry(logging_test_client: TestClient, capfd):
    response = logging_test_client.get("/ok")
    assert response.status_code == 200

    access_entries = [e for e in _entries(capfd) if e.get("event") == "request_completed"]
    assert len(access_entries) == 1
    entry = access_entries[0]
    assert entry["http_method"] == "GET"
    assert entry["http_path"] == "/ok"
    assert entry["http_status"] == 200
    assert isinstance(entry["duration_ms"], int | float)
    assert "body" not in entry


def test_every_emitted_line_is_valid_json(logging_test_client: TestClient, capfd):
    logging_test_client.get("/ok")
    entries = _entries(capfd)
    assert entries  # at least the access-log line; json.loads already validated each


def test_unhandled_exception_logged_and_request_still_returns_response(
    logging_test_client: TestClient, capfd
):
    response = logging_test_client.get("/boom")
    assert response.status_code == 500  # process didn't crash

    entries = _entries(capfd)

    error_entries = [e for e in entries if e.get("level") == "error"]
    assert len(error_entries) == 1
    assert "ValueError" in json.dumps(error_entries[0].get("exception"))

    access_entries = [e for e in entries if e.get("event") == "request_completed"]
    assert len(access_entries) == 1
    assert access_entries[0]["http_status"] == 500
