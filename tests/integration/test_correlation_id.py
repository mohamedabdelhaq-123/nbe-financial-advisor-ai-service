"""Integration tests: correlation-ID isolation across concurrent requests and
propagation into asyncio.gather-based fan-out (mirrors the ingestion
normalizer's chunk-dispatch pattern), captured over real stdout via capfd.
"""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from tests.integration.conftest import build_logging_test_app


def _entries(capfd) -> list[dict]:
    out, _ = capfd.readouterr()
    return [json.loads(line) for line in out.strip().splitlines() if line]


async def test_concurrent_requests_get_distinct_correlation_ids(capfd):
    app = build_logging_test_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(client.get("/ok"), client.get("/ok"))

    assert all(r.status_code == 200 for r in responses)

    access_entries = [e for e in _entries(capfd) if e.get("event") == "request_completed"]
    assert len(access_entries) == 2
    ids = {e["correlation_id"] for e in access_entries}
    assert len(ids) == 2  # each request got its own, no cross-contamination


def test_correlation_id_propagates_through_asyncio_gather_fanout(
    logging_test_client: TestClient, capfd
):
    response = logging_test_client.get("/fanout")
    assert response.status_code == 200

    entries = _entries(capfd)
    chunk_entries = [e for e in entries if e.get("event") == "chunk_processed"]
    access_entries = [e for e in entries if e.get("event") == "request_completed"]

    assert len(chunk_entries) == 3
    assert len(access_entries) == 1
    ids = {e["correlation_id"] for e in chunk_entries} | {access_entries[0]["correlation_id"]}
    assert len(ids) == 1  # every gather-spawned task inherited the request's id
