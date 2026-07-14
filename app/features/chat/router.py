"""Chat slice HTTP surface — internal SSE streaming endpoint."""

from fastapi import APIRouter, Depends, Request

from app.core.security import ERROR_RESPONSES, require_token
from app.features.chat.schemas import ChatTurnRequest
from app.features.chat.service import stream_chat

router = APIRouter(prefix="/internal", tags=["chat"], dependencies=[Depends(require_token)])

# Raw SSE frame examples (one ``data: {json}\\n\\n`` line per event) shown in /docs.
_TOKEN_FRAME = 'data: {"event":"token","data":"You spent "}\n\n'
_DONE_FRAME = (
    'data: {"event":"done","data":{'
    '"content":"You spent 1,240 EGP on groceries last month across 9 transactions.",'
    '"widget":{"type":"allocation_slider","payload":{"allocations":['
    '{"category":"Groceries","percentage":25.0},'
    '{"category":"Rent","percentage":50.0},'
    '{"category":"Savings","percentage":25.0}]}},'
    '"references":[{"target_type":"transaction",'
    '"target_id":"b3f1c2d4-0000-0000-0000-000000000000"}]'
    '}}\n\n'
)
_ERROR_FRAME = 'data: {"event":"error","data":{"message":"Chat not available."}}\n\n'


@router.post(
    "/chat",
    responses={
        200: {
            "description": (
                "A `text/event-stream` of the assistant's reply over the shared envelope "
                "`{\"event\": <type>, \"data\": <payload>}`. Incremental `token` events "
                "stream the reply as it is generated (real path) or as one batch (mock "
                "path, `USE_MOCK_LLM=1` — same envelope, FR-011), followed by exactly one "
                "terminal `done` event carrying the finalized `content`, a `widget` slot "
                "(allocation_slider / product_card / null), and `references` (possibly "
                "empty). The `done` payload carries no message `id` — Django assigns it "
                "after persistence (FR-003). On a production failure exactly one `error` "
                "event is emitted and the stream closes (no `done` follows; FR-010). Not "
                "exercisable via 'Try it out' — use a streaming-aware HTTP client. Wire "
                "contract: specs/009-chat-streaming-contract/contracts/chat-stream.md."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "object",
                        "description": (
                            "One Server-Sent Events frame over the shared "
                            "`{\"event\",\"data\"}` envelope. The stream emits many "
                            "`token` frames, then exactly one terminal `done` (or one "
                            "`error`). Each frame is serialized on the wire as "
                            "`data: {json}\\n\\n`."
                        ),
                        "properties": {
                            "event": {
                                "type": "string",
                                "enum": ["token", "done", "error"],
                                "description": "The event type.",
                            },
                            "data": {
                                "description": (
                                    "For `token`: a string reply fragment. For `done`: a "
                                    "`DonePayload` (content, widget, references; no id). "
                                    "For `error`: an `ErrorPayload` (message)."
                                ),
                            },
                        },
                        "required": ["event", "data"],
                    },
                    "examples": {
                        "token": {
                            "summary": "token event — incremental reply fragment (FR-001)",
                            "value": _TOKEN_FRAME,
                        },
                        "done": {
                            "summary": (
                                "done event — terminal finalized reply with widget + "
                                "references, no id (FR-002/003/005/008)"
                            ),
                            "value": _DONE_FRAME,
                        },
                        "error": {
                            "summary": "error event — production failure; no done follows (FR-010)",
                            "value": _ERROR_FRAME,
                        },
                    },
                }
            },
        },
        **ERROR_RESPONSES,
    },
)
async def chat(body: ChatTurnRequest, request: Request):
    """Send one conversation turn to the Maestro orchestrator and stream its reply.

    The response is a Server-Sent Events stream over the shared ``{"event","data"}``
    envelope: incremental ``token`` events (leaf-agent reply only — Maestro
    classification and summary generation are never forwarded), then exactly one
    terminal ``done`` carrying the finalized ``content``, a ``widget`` slot, and
    ``references`` (no message ``id``; Django assigns it after persistence) — or one
    ``error`` on failure. See
    ``specs/009-chat-streaming-contract/contracts/chat-stream.md``.
    """
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        stream_chat(request.app, body),
        media_type="text/event-stream",
    )
