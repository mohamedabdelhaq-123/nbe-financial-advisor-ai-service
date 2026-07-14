"""OpenAPI shape tests for the chat stream contract (Phase 7, Constitution Principle I).

The wire contract is documented inline at the route level — no hand-rolled
custom-openapi override. The ``/internal/chat`` operation carries an envelope
schema and concrete ``token`` / ``done`` / ``error`` SSE-frame examples under
``text/event-stream``, plus a ``chat`` tag description and app-level version /
description. These tests lock that surface in so ``/docs`` cannot silently drift
from ``specs/009-chat-streaming-contract/contracts/chat-stream.md``.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def openapi(client: TestClient) -> dict:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def _chat_op(schema: dict) -> dict:
    return schema["paths"]["/internal/chat"]["post"]


def test_openapi_reachable(openapi: dict):
    assert openapi["openapi"]


def test_app_info_carries_version_and_description(openapi: dict):
    info = openapi["info"]
    assert info["title"]
    assert info["version"]  # resolved from pyproject.toml
    assert info["description"]


def test_chat_tag_renders_description(openapi: dict):
    tags = {tag["name"]: tag for tag in openapi.get("tags", [])}
    assert "chat" in tags
    assert tags["chat"]["description"]
    assert "chat" in _chat_op(openapi).get("tags", [])


def test_chat_response_documents_envelope_and_examples(openapi: dict):
    sse = _chat_op(openapi)["responses"]["200"]["content"]["text/event-stream"]

    # The shared {event, data} envelope is described as the frame schema.
    envelope = sse["schema"]
    assert envelope["type"] == "object"
    assert {"event", "data"} <= set(envelope["properties"])

    # All three event frames appear as examples.
    examples = sse["examples"]
    assert {"token", "done", "error"} <= set(examples)
    for name in ("token", "done", "error"):
        frame = examples[name]["value"]
        assert frame.startswith("data: ")
        assert '"event"' in frame


def test_done_example_carries_widget_and_references(openapi: dict):
    done_frame = _chat_op(openapi)["responses"]["200"]["content"]["text/event-stream"]["examples"][
        "done"
    ]["value"]
    assert '"event":"done"' in done_frame
    assert '"widget"' in done_frame
    assert '"references"' in done_frame


def test_chat_description_describes_envelope_and_no_id_rule(openapi: dict):
    desc = _chat_op(openapi)["responses"]["200"]["description"]
    # The shared envelope and the terminal done event are described.
    assert "event" in desc
    assert "done" in desc
    # FR-003: the no-message-id rule is surfaced in the docs.
    assert "id" in desc
    # The stale legacy wording has been replaced.
    assert "UTF-8 text chunk" not in desc
