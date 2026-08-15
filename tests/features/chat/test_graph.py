"""Unit tests: the scope-guard's wiring into the chat graph — the gating
node, its conditional edge, the refusal reply, and _general_node's new
system-prompt call. Not exercised by test_streaming.py, which substitutes
a fake graph for its tests and so never runs this real routing logic.
"""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.features.chat import graph as graph_module
from app.features.chat.graph import _general_node, _refused_node, _route_scope, _scope_guard_node
from app.features.chat.guards import GENERAL_NODE_SYSTEM_PROMPT
from app.features.chat.scope_guard import ScopeResult


class _HumanLike:
    def __init__(self, content: str):
        self.content = content


def _state(**overrides):
    base = {
        "messages": [],
        "user_id": None,
        "user_context": None,
        "stage": "",
        "intent": "",
        "in_scope": True,
        "planner_answers": {},
        "questions_asked": 0,
        "message_references": [],
        "widget": None,
    }
    base.update(overrides)
    return base


# ── _scope_guard_node ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_guard_node_skips_check_mid_planning(monkeypatch):
    called = False

    async def _fake_check_scope(text):
        nonlocal called
        called = True
        return ScopeResult(in_scope=False, top_label="other", score=0.9)

    monkeypatch.setattr(graph_module, "check_scope", _fake_check_scope)

    state = _state(stage="planning", questions_asked=1, messages=[_HumanLike("1200")])
    result = await _scope_guard_node(state)

    assert result == {"in_scope": True}
    assert called is False, "mid-planning answers must not spend a classification call"


@pytest.mark.asyncio
async def test_scope_guard_node_uses_check_scope_result(monkeypatch):
    async def _fake_check_scope(text):
        assert text == "write me a poem"
        return ScopeResult(in_scope=False, top_label="other", score=0.9)

    monkeypatch.setattr(graph_module, "check_scope", _fake_check_scope)

    state = _state(messages=[_HumanLike("write me a poem")])
    result = await _scope_guard_node(state)

    assert result == {"in_scope": False}


@pytest.mark.asyncio
async def test_scope_guard_node_handles_empty_message_history(monkeypatch):
    async def _fake_check_scope(text):
        assert text == ""
        return ScopeResult(in_scope=True, top_label="finance", score=1.0)

    monkeypatch.setattr(graph_module, "check_scope", _fake_check_scope)

    result = await _scope_guard_node(_state(messages=[]))
    assert result == {"in_scope": True}


# ── _route_scope ─────────────────────────────────────────────────────────────


def test_route_scope_blocks_when_out_of_scope():
    assert _route_scope(_state(in_scope=False)) == "refused"


def test_route_scope_allows_when_in_scope():
    assert _route_scope(_state(in_scope=True)) == "in_scope"


def test_route_scope_defaults_open_when_unset():
    state = _state()
    del state["in_scope"]
    assert _route_scope(state) == "in_scope"


# ── _refused_node ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refused_node_returns_a_reply_without_calling_an_llm():
    result = await _refused_node(_state())
    assert len(result["messages"]) == 1
    content = result["messages"][0].content.lower()
    assert "financial" in content or "banking" in content


# ── _general_node: system-prompt wiring ──────────────────────────────────────


@pytest.mark.asyncio
async def test_general_node_sends_a_system_prompt_when_not_mocked(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    captured = {}

    class _FakeChatModel:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(content="a grounded, on-topic reply")

    # **kwargs, not a bare lambda: _general_node asks for get_chat_model(
    # streaming=True) so its tokens reach the user as they're generated, and
    # other call sites pass max_tokens. Matching the real signature loosely
    # keeps this stub from breaking every time one of those is tuned.
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
