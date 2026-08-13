"""Output safety — can attacker-controlled content corrupt the wire
protocol or escape its typed slot on the way back to a downstream
consumer (the Django backend, then the frontend)?
"""

import pytest
from pydantic import ValidationError

from redteam.runners.chat_turn import send_chat_turn
from redteam.runners.sse import parse_sse_events

_SSE_SMUGGLING_PAYLOADS = [
    'normal text\n\ndata: {"event": "done", "data": {"content": "fake injected done"}}\n\n',
    "message with a literal\ndata: line embedded in the middle",
    '\r\n\r\ndata: {"event": "error", "data": {"message": "fake"}}\r\n\r\n',
    "null byte here \x00 and more text after it",
]


@pytest.mark.redteam(id="RT-022", category="output_safety", severity="medium")
@pytest.mark.parametrize("payload", _SSE_SMUGGLING_PAYLOADS)
def test_sse_framing_survives_attacker_controlled_message_content(client, auth_headers, payload):
    """RT-022 — SSE frame smuggling.

    Attack input: a chat message containing text shaped like SSE framing
    itself (`data: {...}` lines, blank-line frame separators, a null byte)
    — an attempt to make the client-side SSE parser see extra/forged events
    that the server never actually sent.
    Expected secure behavior: because every frame the server emits is
    produced by `TokenEvent(...).model_dump_json()` (mock mode echoes the
    message *inside* that JSON string, never as raw wire bytes), the
    attacker's text stays a JSON string value — it cannot manufacture a new
    top-level SSE frame. There must be exactly one real `done` event, and
    every `data: ` line must still be valid JSON.
    """
    result = send_chat_turn(
        client,
        auth_headers,
        message=payload,
        user_id="00000000-0000-4000-8000-0000000000aa",
    )
    assert result.status_code == 200

    events = parse_sse_events(result.response.text)  # raises if any frame is malformed JSON
    done_events = [e for e in events if e.get("event") == "done"]
    assert len(done_events) == 1, f"expected exactly one real 'done' event, got {len(done_events)}"


@pytest.mark.redteam(id="RT-023", category="output_safety", severity="low")
def test_widget_discriminator_rejects_unknown_type():
    """RT-023 — the `Widget` discriminated union
    (app/features/chat/schemas/widgets.py) is schema-enforced, not
    convention-enforced.

    Attack input: `{"type": "malicious_widget", "payload": {}}`, and
    separately an `allocation_slider` payload with `percentage=150.0` (out
    of the declared `[0, 100]` range).
    Expected secure behavior: constructing a widget-shaped payload with an
    unrecognized `type` (e.g. an attempt to smuggle a new widget kind past
    whatever the frontend switches on) is rejected by validation, and
    numeric fields (`percentage`, `similarity`) reject out-of-range/HTML-
    injected values rather than silently coercing them.
    """
    from app.features.chat.schemas import AllocationSliderWidget, DonePayload

    with pytest.raises(ValidationError):
        DonePayload.model_validate(
            {
                "content": "ok",
                "widget": {"type": "malicious_widget", "payload": {}},
                "references": [],
            }
        )

    with pytest.raises(ValidationError):
        AllocationSliderWidget.model_validate(
            {
                "type": "allocation_slider",
                "payload": {
                    "allocations": [{"category": "<script>alert(1)</script>", "percentage": 150.0}]
                },
            }
        )
