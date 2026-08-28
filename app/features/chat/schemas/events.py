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


class ToolCallPayload(BaseModel):
    """One tool call's lifecycle signal, carried by a `tool_call` event."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"call_id": "call_abc123", "tool": "get_transactions", "status": "started"}
            ]
        }
    )

    call_id: str = Field(description="Correlates a `started` signal with its matching `completed`.")
    tool: str = Field(
        description=(
            "Internal tool identifier (e.g. `get_transactions`). Never shown raw to the "
            "user — a client maps it to a friendly label."
        )
    )
    status: Literal["started", "completed"] = Field(
        description="Whether the tool call was just made, or has just returned."
    )


class ToolCallEvent(BaseModel):
    """Zero or more of these may interleave with `token` events, currently only during the
    `analysis` node's tool-calling loop. Best-effort/informational: absence is normal for
    turns that don't call a tool, and a client must not depend on this for correctness."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event": "tool_call",
                    "data": {
                        "call_id": "call_abc123",
                        "tool": "get_transactions",
                        "status": "started",
                    },
                }
            ]
        }
    )

    event: Literal["tool_call"] = Field(
        default="tool_call",
        description="The event type; always `tool_call` for a tool lifecycle signal.",
    )
    data: ToolCallPayload = Field(description="The tool call lifecycle payload.")


class AgentSelectedPayload(BaseModel):
    """The specialist Maestro routed this turn to — carried by a single-shot
    `agent_selected` event. Never a raw graph-node/internal identifier — the
    same route name documented in routing.py's ROUTE_SPECS/route_catalogue()."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"agent": "analysis"}]})

    agent: str = Field(
        description=(
            "Route name of the specialist selected for this turn (analysis, "
            "planning, investment_planning, recommendation, general). Never "
            "emitted for clarify/refuse turns, which delegate to no specialist."
        )
    )


class AgentSelectedEvent(BaseModel):
    """At most one per turn — emitted as soon as evidence of Maestro's
    routing decision exists (the first leaf-node chunk, or the interrupt
    fallback for a first-entry planner_ask/investment_plan turn), always
    before any token/tool_call event for that turn. Absent for clarify/
    refuse turns."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"event": "agent_selected", "data": {"agent": "analysis"}}]}
    )

    event: Literal["agent_selected"] = Field(
        default="agent_selected",
        description="The event type; always `agent_selected` for a routing-decision signal.",
    )
    data: AgentSelectedPayload = Field(description="The selected agent's route name.")


class DonePayload(BaseModel):
    """The finalized reply carried by the terminal `done` event."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "content": "You spent 1,240 EGP on groceries last month.",
                    "widget": None,
                    "references": [],
                    "suggestions": [
                        "Which category grew the most this month?",
                        "How can I cut down on dining expenses?",
                        "Compare this to last month",
                    ],
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
            "Citations to underlying financial records; empty list when the reply is not grounded."
        ),
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description=(
            "Up to 3 short follow-up prompts the user might send next, grounded in this "
            "reply. Always present; MAY be empty if generation failed."
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
                        "suggestions": [
                            "Which category grew the most this month?",
                            "How can I cut down on dining expenses?",
                            "Compare this to last month",
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
            "The finalized reply payload (content, widget, references, suggestions). "
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
