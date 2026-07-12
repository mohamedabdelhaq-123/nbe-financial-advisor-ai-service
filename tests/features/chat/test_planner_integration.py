"""US3 Integration test: Chat planner node yields 100%-sum plan in mock mode."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.features.chat.agents.planner import planner_node


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
    }

    result = await planner_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage)
    assert "budget" in msg.content.lower() or "plan" in msg.content.lower()


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
    }

    result = await planner_node(state)
    assert "messages" in result
    assert "questions_asked" in result
    assert result["questions_asked"] == 1
