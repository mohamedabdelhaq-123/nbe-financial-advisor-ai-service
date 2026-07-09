"""Chat slice HTTP surface."""

from fastapi import APIRouter, Depends

from app.core.security import require_token
from app.features.chat.schemas import ChatRequest, ChatResponse
from app.features.chat.service import generate_reply

router = APIRouter(tags=["chat"], dependencies=[Depends(require_token)])


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """Return an LLM reply to a user message. Requires a valid Bearer token."""
    return await generate_reply(body.message)
