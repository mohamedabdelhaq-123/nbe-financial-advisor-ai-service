"""Parses the chat endpoint's `text/event-stream` body into typed frames.

Generalizes the ad hoc `_extract_done_payload` helper in
`tests/features/chat/test_chat.py` into something every scenario module can
share, plus a couple of structural checks (frame count, well-formed JSON per
line) that matter specifically for output-safety/SSE-smuggling scenarios.
"""

import json
from typing import Any


def parse_sse_events(body: str) -> list[dict[str, Any]]:
    """Return every `{"event": ..., "data": ...}` frame in the SSE body, in order.

    Raises `AssertionError` (not a silent skip) if a `data: ` line isn't
    valid JSON — an attacker-controlled payload corrupting the wire framing
    is exactly the failure mode `test_rt_output_safety` scenarios check for.
    """
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :]
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"SSE frame is not valid JSON: {raw!r}") from exc
    return events


def get_event(body: str, event_type: str) -> dict[str, Any] | None:
    """Return the first frame's `data` payload matching `event_type`, or None."""
    for event in parse_sse_events(body):
        if event.get("event") == event_type:
            return event.get("data")
    return None


def get_done_payload(body: str) -> dict[str, Any]:
    payload = get_event(body, "done")
    if payload is None:
        raise AssertionError("no 'done' event in SSE body")
    return payload
