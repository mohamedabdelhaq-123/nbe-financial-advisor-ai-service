"""Streaming-edge tests for the real (non-mock) chat stream path.

These tests bypass mock mode and drive ``stream_chat`` directly against a fake
compiled graph, asserting the {event, data} envelope, the leaf-only token
filter, the terminal ``done`` assembly, the error event, and client-disconnect
handling. No live model or network call is made (Constitution Principle I).
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.features.chat.schemas import (
    AllocationSliderWidget,
    ChatTurnRequest,
    Reference,
)
from app.features.chat.service import stream_chat

_LEAF_NODES = ("analysis", "planner", "recommendation", "general")


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeSnapshot:
    def __init__(self, values):
        self.values = values


class _FakeGraph:
    """Minimal stand-in for a compiled LangGraph, configurable per scenario."""

    def __init__(self, *, chunks=None, state_values=None, raise_in_stream=None):
        self._chunks = chunks or []
        self._state_values = state_values or {}
        self._raise_in_stream = raise_in_stream

    async def astream(self, state, config=None, stream_mode="messages", **kwargs):
        for content, node in self._chunks:
            yield (_FakeChunk(content), {"langgraph_node": node})
        if self._raise_in_stream is not None:
            raise self._raise_in_stream("forced failure")

    async def aget_state(self, config=None):
        return _FakeSnapshot(self._state_values)


def _fake_app():
    return SimpleNamespace(state=SimpleNamespace(checkpointer=object()))


def _request(message="hi", is_first_turn=True):
    return ChatTurnRequest(
        conversation_id="t-conv",
        user_id=1,
        message=message,
        is_first_turn=is_first_turn,
    )


async def _collect(app, request):
    frames = []
    async for frame in stream_chat(app, request):
        frames.append(frame)
    return frames


def _parse(frames):
    events = []
    for frame in frames:
        line = frame.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


def _install_fake_graph(monkeypatch, graph):
    monkeypatch.setattr(
        "app.features.chat.graph.build_graph", lambda checkpointer=None: graph
    )


@pytest.fixture
def real_mode(monkeypatch):
    """Disable the mock short-circuit so the graph streaming path is exercised."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "use_mock_llm", False)
    return _fake_app()


# --- T014: incremental streaming + leaf-only filter --------------------------


@pytest.mark.asyncio
async def test_more_than_one_token_event_before_done(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[
            ("planning", "maestro"),  # classification word — must NOT be forwarded
            ("You ", "general"),
            ("spent ", "general"),
            ("100 EGP.", "general"),
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))

    tokens = [e for e in events if e["event"] == "token"]
    dones = [e for e in events if e["event"] == "done"]

    assert len(tokens) > 1, "expected incremental (>1) token events"
    assert len(dones) == 1
    # Leaf-only filter: the Maestro classification word never reaches the stream.
    assert all(t["data"] != "planning" for t in tokens)
    assert "".join(t["data"] for t in tokens) == "You spent 100 EGP."


@pytest.mark.asyncio
async def test_non_leaf_node_tokens_are_not_forwarded(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[
            ("summary-text", "summarize"),  # internal — must be filtered
            ("intent-word", "maestro"),  # internal — must be filtered
            ("leaf-reply", "analysis"),  # leaf — forwarded
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    tokens = [e["data"] for e in events if e["event"] == "token"]
    assert tokens == ["leaf-reply"]


# --- T014a: streaming edge cases ---------------------------------------------


@pytest.mark.asyncio
async def test_error_event_no_done_follows(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[("partial", "general")],
        state_values={"messages": []},
        raise_in_stream=RuntimeError,
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    errors = [e for e in events if e["event"] == "error"]
    dones = [e for e in events if e["event"] == "done"]

    assert len(errors) == 1
    assert "forced failure" in errors[0]["data"]["message"]
    assert dones == [], "no done event must follow an error"


@pytest.mark.asyncio
async def test_empty_content_still_emits_done(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[],  # no leaf tokens
        state_values={"messages": [type("M", (), {"content": ""})()]},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    dones = [e for e in events if e["event"] == "done"]

    assert len(dones) == 1
    assert dones[0]["data"]["content"] == ""
    assert dones[0]["data"]["widget"] is None
    assert dones[0]["data"]["references"] == []


@pytest.mark.asyncio
async def test_widget_and_references_combo_in_done(real_mode, monkeypatch):
    widget = AllocationSliderWidget.model_validate(
        {
            "type": "allocation_slider",
            "payload": {"allocations": [{"category": "housing", "percentage": 100}]},
        }
    )
    refs = [Reference(target_type="transaction", target_id="b3f1c2d4-0000-0000-0000-000000000000")]
    graph = _FakeGraph(
        chunks=[("plan ready", "planner")],
        state_values={
            "messages": [type("M", (), {"content": "plan ready"})()],
            "widget": widget,
            "message_references": refs,
        },
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    dones = [e for e in events if e["event"] == "done"]

    assert len(dones) == 1
    data = dones[0]["data"]
    assert data["widget"]["type"] == "allocation_slider"
    assert data["widget"]["payload"]["allocations"][0]["category"] == "housing"
    assert len(data["references"]) == 1
    assert data["references"][0]["target_type"] == "transaction"
    assert data["references"][0]["target_id"] == "b3f1c2d4-0000-0000-0000-000000000000"
    assert "id" not in data


@pytest.mark.asyncio
async def test_client_disconnect_stops_with_no_done(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[("first ", "general"), ("second", "general")],
        state_values={"messages": []},
        raise_in_stream=asyncio.CancelledError,
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    tokens = [e for e in events if e["event"] == "token"]
    dones = [e for e in events if e["event"] == "done"]
    errors = [e for e in events if e["event"] == "error"]

    # Some tokens were produced before the disconnect, but no done/error follows.
    assert len(tokens) >= 1
    assert dones == []
    assert errors == []


@pytest.mark.asyncio
async def test_token_envelope_uses_event_data_shape(real_mode, monkeypatch):
    graph = _FakeGraph(chunks=[("hi", "general")], state_values={"messages": []})
    _install_fake_graph(monkeypatch, graph)

    frames = await _collect(real_mode, _request())
    token_frames = [f for f in frames if '"event": "token"' in f or '"event":"token"' in f]

    assert len(token_frames) >= 1
    # No legacy ad-hoc envelope shapes leak through (widget "type" is fine).
    for frame in frames:
        assert "[DONE]" not in frame
        assert '"type": "token"' not in frame
        assert '"type": "error"' not in frame


# --- T015: real-Postgres multi-turn typed-state round-trip -------------------
# Exercises the real AsyncPostgresSaver checkpointer (Testcontainers) to confirm
# typed widget/message_references Pydantic values survive serialization and that
# multi-turn routing resumes state correctly (FR-012). Mock-mode nodes only — no
# live model call (Constitution Principle I).


@pytest.mark.asyncio
async def test_multi_turn_typed_state_survives_real_postgres(own_db_url):
    pytest.importorskip("psycopg_pool")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    psycopg_url = own_db_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = AsyncConnectionPool(conninfo=psycopg_url, kwargs={"autocommit": True}, open=False)
    await pool.open()
    try:
        saver = AsyncPostgresSaver(conn=pool)  # type: ignore[arg-type]
        await saver.setup()

        from app.features.chat.graph import build_graph

        graph = build_graph(checkpointer=saver)

        # --- Part A: typed widget + references survive the checkpointer round-trip.
        config_a = {"configurable": {"thread_id": "conv-t15-typed"}}
        widget = AllocationSliderWidget.model_validate(
            {
                "type": "allocation_slider",
                "payload": {
                    "allocations": [
                        {"category": "housing", "percentage": 60},
                        {"category": "food", "percentage": 40},
                    ]
                },
            }
        )
        refs = [
            Reference(
                target_type="transaction",
                target_id="b3f1c2d4-0000-0000-0000-000000000001",
            )
        ]
        state_a = {
            "messages": ["hi"],
            "user_context": {},
            "stage": "",
            "intent": "",
            "planner_answers": {},
            "questions_asked": 0,
            "message_references": refs,
            "widget": widget,
        }
        await graph.ainvoke(state_a, config_a)
        snap = await graph.aget_state(config_a)
        round_tripped_widget = snap.values.get("widget")
        round_tripped_refs = snap.values.get("message_references") or []

        assert round_tripped_widget is not None
        assert isinstance(round_tripped_widget, AllocationSliderWidget)
        assert round_tripped_widget.payload.allocations[0].category == "housing"
        assert len(round_tripped_refs) == 1
        assert isinstance(round_tripped_refs[0], Reference)
        assert round_tripped_refs[0].target_type == "transaction"
        assert round_tripped_refs[0].target_id.endswith("0001")

        # --- Part B: multi-turn planner routing resumes and captures answers.
        config_b = {"configurable": {"thread_id": "conv-t15-planner"}}

        state_first = {
            "messages": ["help me budget"],
            "user_context": {},
            "stage": "",
            "intent": "",
            "planner_answers": {},
            "questions_asked": 0,
            "message_references": [],
            "widget": None,
        }
        await graph.ainvoke(state_first, config_b)
        snap1 = await graph.aget_state(config_b)
        assert snap1.values.get("stage") == "planning"
        qa_after_first = snap1.values.get("questions_asked", 0)
        assert qa_after_first > 0

        # Non-first turn: restore persisted state and supply an answer (mirrors
        # the resumption logic in service.py).
        prev = snap1.values
        planner_answers = dict(prev.get("planner_answers") or {})
        qa = prev.get("questions_asked", 0)
        if qa > 0 and prev.get("stage") != "plan_complete":
            from app.features.plan.service import QUESTIONS

            idx = qa - 1
            if idx < len(QUESTIONS):
                planner_answers.setdefault(QUESTIONS[idx].id, "about 4000")

        state_second = {
            "messages": ["about 4000"],
            "user_context": {},
            "stage": prev.get("stage", ""),
            "intent": "",
            "planner_answers": planner_answers,
            "questions_asked": qa,
            "message_references": [],
            "widget": None,
        }
        await graph.ainvoke(state_second, config_b)
        snap2 = await graph.aget_state(config_b)

        # The questionnaire advanced (the answer was captured, not lost).
        assert snap2.values.get("questions_asked", 0) > qa_after_first
    finally:
        await pool.close()
