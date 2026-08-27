"""Unit tests for routing outcomes and terminal chat nodes."""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.features.chat.graph import (
    _clarify_node,
    _general_node,
    _refused_node,
    _route_intent,
)
from app.features.chat.guards import GENERAL_NODE_SYSTEM_PROMPT


class _HumanLike:
    def __init__(self, content: str):
        self.content = content


def _state(**overrides):
    base = {
        "messages": [],
        "user_id": None,
        "user_context": None,
        "stage": "",
        "intent": "general",
        "in_scope": True,
        "routing_outcome": "route",
        "routing_confidence": 1.0,
        "routing_clarification": None,
        "planner_answers": {},
        "questions_asked": 0,
        "message_references": [],
        "widget": None,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("intent", "node"),
    [
        ("analysis", "analysis"),
        ("planning", "planner_ask"),
        ("investment_planning", "investment_plan"),
        ("recommendation", "recommendation"),
        ("general", "general"),
    ],
)
def test_route_intent_uses_central_route_catalogue(intent, node):
    assert _route_intent(_state(intent=intent)) == node


def test_route_intent_sends_refusal_outcome_to_refused_node():
    assert _route_intent(_state(routing_outcome="refuse")) == "refused"


def test_route_intent_sends_low_confidence_outcome_to_clarify_node():
    assert _route_intent(_state(routing_outcome="clarify")) == "clarify"


def test_route_intent_falls_back_to_general_for_unknown_route():
    assert _route_intent(_state(intent="not-configured")) == "general"


@pytest.mark.asyncio
async def test_refused_node_returns_a_finance_redirect_without_calling_an_llm():
    result = await _refused_node(_state())
    assert len(result["messages"]) == 1
    content = result["messages"][0].content.lower()
    assert "financial" in content or "banking" in content
    assert result["intent"] == "refused"
    assert result["routing_outcome"] == "refuse"


@pytest.mark.asyncio
async def test_clarify_node_uses_maestros_short_question_without_another_llm_call():
    question = "Do you want to review spending or create a new budget?"
    result = await _clarify_node(_state(routing_clarification=question))
    assert result["messages"][0].content == question
    assert result["intent"] == "clarify"
    assert result["routing_outcome"] == "clarify"


@pytest.mark.asyncio
async def test_general_node_sends_a_system_prompt_when_not_mocked(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    captured = {}

    class _FakeChatModel:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(content="a grounded, on-topic reply")

    monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: _FakeChatModel())

    state = _state(messages=[_HumanLike("what can you help me with?")])
    result = await _general_node(state)

    sent = captured["messages"]
    assert len(sent) == 2
    assert sent[0].content == GENERAL_NODE_SYSTEM_PROMPT
    assert sent[1].content == "what can you help me with?"
    assert result["messages"][0].content == "a grounded, on-topic reply"


@pytest.mark.asyncio
async def test_general_node_mock_mode_echoes_without_calling_llm(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", True)

    state = _state(messages=[_HumanLike("hello")])
    result = await _general_node(state)

    assert "hello" in result["messages"][0].content
