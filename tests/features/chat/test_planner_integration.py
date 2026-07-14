"""US3 Integration test: Chat planner node yields 100%-sum plan in mock mode."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.features.chat.agents.planner import planner_node
from app.features.chat.schemas import AllocationSliderWidget


@pytest.mark.asyncio
async def test_planner_route_completes_with_valid_plan():
    state = {
        "messages": [HumanMessage(content="help me budget")],
        "user_context": {"monthly_income": 5000},
        "stage": "planner",
        "intent": "planning",
        "planner_answers": {},
        "questions_asked": 7,
        "message_references": [],
        "widget": None,
    }

    result = await planner_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage)
    assert "budget" in msg.content.lower() or "plan" in msg.content.lower()

    # FR-005: a completed plan carries an allocation_slider widget summing to 100.
    widget = result.get("widget")
    assert isinstance(widget, AllocationSliderWidget)
    assert widget.type == "allocation_slider"
    total = sum(a.percentage for a in widget.payload.allocations)
    assert total == 100


@pytest.mark.asyncio
async def test_planner_route_asks_question_when_not_complete():
    state = {
        "messages": [HumanMessage(content="help me budget")],
        "user_context": {},
        "stage": "planner",
        "intent": "planning",
        "planner_answers": {},
        "questions_asked": 0,
        "message_references": [],
        "widget": None,
    }

    result = await planner_node(state)
    assert "messages" in result
    assert "questions_asked" in result
    assert result["questions_asked"] == 1
    # While still asking questions, the widget is not set (stays None).
    assert result.get("widget") is None
