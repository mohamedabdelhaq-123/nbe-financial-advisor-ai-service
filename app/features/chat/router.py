"""Chat slice HTTP surface — internal SSE streaming endpoint."""

from fastapi import APIRouter, Depends, Request

from app.core.security import ERROR_RESPONSES, require_token
from app.features.chat.schemas import ChatTurnRequest
from app.features.chat.service import stream_chat

router = APIRouter(prefix="/internal", tags=["chat"], dependencies=[Depends(require_token)])


@router.post(
    "/chat",
    responses={
        200: {
            "description": (
                "A `text/event-stream` of Maestro's response, streamed as it is generated. "
                "Each event is a UTF-8 text chunk of the assistant's reply; the stream ends "
                "when the connection closes. Not fully exercisable via 'Try it out' — use a "
                "streaming-aware HTTP client to consume it."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **ERROR_RESPONSES,
    },
)
async def chat(body: ChatTurnRequest, request: Request):
    """Send one conversation turn to the Maestro orchestrator and stream its reply.

    Routes the message through intent-based sub-agent delegation and returns the
    response as a Server-Sent Events stream rather than a single JSON body.
    """
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        stream_chat(request.app, body),
        media_type="text/event-stream",
    )
