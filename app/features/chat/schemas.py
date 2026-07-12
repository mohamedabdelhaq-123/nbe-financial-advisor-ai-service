"""Request/response contracts for the chat slice — internal SSE streaming."""

from pydantic import BaseModel


class ChatTurnRequest(BaseModel):
    conversation_id: str
    user_id: int
    message: str
    is_first_turn: bool = False
    initial_context: dict | None = None
    refresh_context: bool = False
