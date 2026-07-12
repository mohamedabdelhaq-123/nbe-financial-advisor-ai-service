"""Chat slice HTTP surface — internal SSE streaming endpoint."""

from fastapi import APIRouter, Depends, Request

from app.core.security import require_token
from app.features.chat.schemas import ChatTurnRequest
from app.features.chat.service import stream_chat

router = APIRouter(prefix="/internal", tags=["chat"], dependencies=[Depends(require_token)])


@router.post("/chat")
async def chat(body: ChatTurnRequest, request: Request):
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        stream_chat(request.app, body),
        media_type="text/event-stream",
    )
