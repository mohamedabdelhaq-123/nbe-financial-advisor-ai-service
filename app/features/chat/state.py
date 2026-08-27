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
    in_scope: bool
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
