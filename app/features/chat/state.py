"""Conversation state definition for the LangGraph chat pipeline."""

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.features.chat.schemas import Reference, Widget


class ConversationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_context: dict
    stage: str
    intent: str
    planner_answers: dict
    questions_asked: int
    message_references: list[Reference]
    widget: Widget | None
