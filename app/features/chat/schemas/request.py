"""Request contracts for the chat slice — internal SSE streaming."""

from pydantic import BaseModel, ConfigDict, Field


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "conversation_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
                    "user_id": 1001,
                    "message": "How much did I spend on groceries last month?",
                    "is_first_turn": False,
                    "initial_context": None,
                    "refresh_context": False,
                }
            ]
        }
    )

    conversation_id: str = Field(
        description="Stable identifier for the chat thread; used to key persisted turns.",
        examples=["3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f"],
    )
    user_id: int = Field(
        description="Backend user ID the conversation belongs to.",
        examples=[1001],
    )
    message: str = Field(
        description="The user's message for this turn.",
        examples=["How much did I spend on groceries last month?"],
    )
    is_first_turn: bool = Field(
        default=False,
        description="Whether this is the first turn of the conversation (skips history lookup).",
    )
    initial_context: dict | None = Field(
        default=None,
        description="Optional seed context (e.g. account summary) supplied only on the first turn.",
    )
    refresh_context: bool = Field(
        default=False,
        description="Force a reload of the user's financial context instead of using the cache.",
    )
