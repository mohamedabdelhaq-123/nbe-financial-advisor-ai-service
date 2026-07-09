"""
Chat business logic.

This is the seed of the future Maestro-orchestrated assistant. For now it is a
single LLM round-trip. In mock mode it returns a canned reply in the exact same
shape as the real path, so tests and callers cannot tell the difference and no
model/network call is ever made.
"""

from fastapi import HTTPException

from app.core.config import settings
from app.core.llm import get_chat_model
from app.features.chat.schemas import ChatResponse


async def generate_reply(message: str) -> ChatResponse:
    """Produce a reply to a user message via the configured LLM."""
    if settings.use_mock_llm:
        return ChatResponse(reply=f"This is a mock response to: {message}")

    try:
        result = await get_chat_model().ainvoke(message)
    except Exception as exc:  # surface provider failures as a bad-gateway
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    content = result.content
    reply = content if isinstance(content, str) else str(content)
    return ChatResponse(reply=reply)
