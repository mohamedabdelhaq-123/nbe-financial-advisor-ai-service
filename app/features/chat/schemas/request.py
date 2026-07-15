"""Request contracts for the chat slice — internal SSE streaming."""

from pydantic import UUID4, BaseModel, ConfigDict, Field


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "conversation_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
                    "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
                    "message": "How much did I spend on groceries last month?",
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
    user_id: UUID4 = Field(
        description="Backend user ID the conversation belongs to.",
        examples=["7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"],
    )
    message: str = Field(
        description="The user's message for this turn.",
        examples=["How much did I spend on groceries last month?"],
    )
    initial_context: dict | None = Field(
        default=None,
        description=(
            "Optional context for the conversation (e.g. account summary). Unrelated to "
            "identity — the user is always identified by `user_id` above. If omitted, any "
            "context already stored for this conversation is kept unchanged."
        ),
    )
    refresh_context: bool = Field(
        default=False,
        description="Force a reload of the user's financial context instead of using the cache.",
    )
