"""Conversation state definition for the LangGraph chat pipeline."""

import uuid
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.features.chat.schemas import Reference, Widget


class ConversationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: uuid.UUID
    user_context: dict | None
    stage: str
    intent: str
    # The route name of the last capability that actually produced a `route`
    # outcome — unlike `intent` (overwritten to "clarify"/"refused" by those
    # outcomes, and read by scope_guard.py as last-turn telemetry), this key
    # is simply absent from a clarify/refuse turn's state update, so it
    # survives those turns — and the whole interrupt-resume loop, which never
    # runs maestro_node at all — unchanged. Lets Maestro's classifier weigh
    # "is this a follow-up about what that agent just said" against "is this
    # a fresh request for a different specialist" instead of re-routing any
    # message that happens to share a keyword with another route's
    # description. See agents/maestro.py's _decision_state().
    last_active_route: str | None
    in_scope: bool
    routing_outcome: str
    routing_confidence: float
    routing_clarification: str | None
    planner_answers: dict
    questions_asked: int
    last_question_id: str | None
    planner_validation_attempts: int
    planner_context: dict | None
    stated_savings_goal: str | None
    investment_answers: dict
    investment_context: dict | None
    investment_validation_attempts: int
    investment_validation_reason: str | None
    pending_answer: str | None
    pending_validation_reason: str | None
    message_references: list[Reference]
    widget: Widget | None
