"""SSE stream-event envelopes for the chat slice.

Each model serializes to one ``data: {json}\\n\\n`` line via
``model_dump_json()``. The shared envelope is ``{"event": <type>, "data": <payload>}``.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.chat.schemas.references import Reference
from app.features.chat.schemas.widgets import Widget


class TokenEvent(BaseModel):
    """An incremental fragment of the assistant's reply, streamed as it is generated."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"event": "token", "data": "You spent "}]}
    )

    event: Literal["token"] = Field(
        default="token",
        description="The event type; always `token` for an incremental reply fragment.",
    )
    data: str = Field(description="A small fragment of the assistant's reply text.")


class DonePayload(BaseModel):
    """The finalized reply carried by the terminal `done` event."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "content": "You spent 1,240 EGP on groceries last month.",
                    "widget": None,
                    "references": [],
                }
            ]
        }
    )

    content: str = Field(
        description="The complete finalized reply text; MAY be empty but is always present."
    )
    widget: Widget | None = Field(
        default=None,
        description=(
            "Structured UI element for the reply (allocation_slider / product_card), "
            "or null. Always present."
        ),
    )
    references: list[Reference] = Field(
        default_factory=list,
        description=(
            "Citations to underlying financial records; empty list when the reply "
            "is not grounded."
        ),
    )


class DoneEvent(BaseModel):
    """The terminal event — exactly one per turn, emitted after the stream drains."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event": "done",
                    "data": {
                        "content": (
                            "You spent 1,240 EGP on groceries last month across 9 transactions."
                        ),
                        "widget": None,
                        "references": [
                            {
                                "target_type": "transaction",
                                "target_id": "b3f1c2d4-0000-0000-0000-000000000000",
                            },
                        ],
                    },
                }
            ]
        }
    )

    event: Literal["done"] = Field(
        default="done",
        description="The event type; always `done` for the terminal finalized reply.",
    )
    data: DonePayload = Field(
        description=(
            "The finalized reply payload (content, widget, references). "
            "Carries no message `id` (FR-003)."
        )
    )


class ErrorPayload(BaseModel):
    """The error detail carried by an `error` event."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"message": "Chat not available."}]})

    message: str = Field(description="A human-readable description of the failure.")


class ErrorEvent(BaseModel):
    """An error event — at most one per turn, after which the stream closes (no `done` follows)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"event": "error", "data": {"message": "Chat not available."}}]
        }
    )

    event: Literal["error"] = Field(
        default="error",
        description="The event type; always `error` for a production failure.",
    )
    data: ErrorPayload = Field(description="The error detail payload.")
