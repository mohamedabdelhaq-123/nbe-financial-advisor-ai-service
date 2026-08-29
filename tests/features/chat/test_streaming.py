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
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.features.chat.schemas import (
    AllocationSliderWidget,
    ChatTurnRequest,
    Reference,
)
from app.features.chat.service import stream_chat

_LEAF_NODES = ("analysis", "planner_ask", "validate_answer", "recommendation", "general")


class _FakeChunk(AIMessage):
    def __init__(self, content):
        super().__init__(content=content)


class _FakeSnapshot:
    def __init__(self, values, interrupts=()):
        self.values = values
        self.interrupts = interrupts


class _FakeGraph:
    """Minimal stand-in for a compiled LangGraph, configurable per scenario."""

    def __init__(self, *, chunks=None, state_values=None, raise_in_stream=None, interrupts=()):
        self._chunks = chunks or []
        self._state_values = state_values or {}
        self._raise_in_stream = raise_in_stream
        self._interrupts = interrupts

    async def astream(self, state, config=None, stream_mode="messages", **kwargs):
        for entry in self._chunks:
            # Accepts either (content, node) or (content, node, tags) — the
            # 3-tuple form simulates an internally-tagged LLM call (see
            # app.core.llm.INTERNAL_CALL_TAG) without touching every
            # existing 2-tuple chunk fixture across this file.
            content, node, *rest = entry
            tags = rest[0] if rest else None
            message = content if isinstance(content, BaseMessage) else _FakeChunk(content)
            metadata = {"langgraph_node": node}
            if tags:
                metadata["tags"] = tags
            yield (message, metadata)
        if self._raise_in_stream is not None:
            raise self._raise_in_stream("forced failure")

    async def aget_state(self, config=None):
        return _FakeSnapshot(self._state_values, interrupts=self._interrupts)


def _fake_app():
    return SimpleNamespace(state=SimpleNamespace(checkpointer=object()))


def _request(message="hi"):
    return ChatTurnRequest(
        conversation_id="t-conv",
        user_id="7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
        message=message,
    )


@pytest.fixture(autouse=True)
def allow_owned_conversation(monkeypatch):
    """Streaming tests focus on SSE behavior after authorization succeeds."""

    async def _allowed(conversation_id, user_id):
        return True

    monkeypatch.setattr(
        "app.features.chat.service._conversation_belongs_to_user",
        _allowed,
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
    monkeypatch.setattr("app.features.chat.graph.build_graph", lambda checkpointer=None: graph)


@pytest.fixture
def real_mode(monkeypatch):
    """Disable the mock short-circuit so the graph streaming path is exercised."""
    from app.core.config import settings
    from app.features.chat import suggestions as suggestions_module

    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    # Suggestion generation calls a real LLM once mock mode is off — stub it so
    # these tests keep exercising only the streaming/done-assembly path, with
    # no live model/network call (Constitution Principle I).
    async def _fake_generate_suggestions(content, widget):
        return ["s1", "s2", "s3"]

    monkeypatch.setattr(suggestions_module, "generate_suggestions", _fake_generate_suggestions)
    return _fake_app()


@pytest.mark.asyncio
async def test_unowned_conversation_is_rejected_before_graph_access(monkeypatch):
    async def _denied(conversation_id, user_id):
        return False

    monkeypatch.setattr(
        "app.features.chat.service._conversation_belongs_to_user",
        _denied,
    )
    events = _parse(await _collect(_fake_app(), _request()))

    assert events == [
        {
            "event": "error",
            "data": {"message": "Conversation not available."},
        }
    ]


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


@pytest.mark.asyncio
async def test_resumed_human_message_is_not_echoed_as_token(real_mode, monkeypatch):
    """Regression: planner_ask_node re-appends the user's own answer to history
    on interrupt() resume — that HumanMessage must never be forwarded as a
    token even though "planner_ask" is a leaf node."""
    graph = _FakeGraph(
        chunks=[
            (HumanMessage(content="wtf"), "planner_ask"),  # user's own resumed answer
            ("real reply", "planner_ask"),  # actual assistant output
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    tokens = [e["data"] for e in events if e["event"] == "token"]
    assert tokens == ["real reply"]


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
    assert errors[0]["data"]["message"] == "Something went wrong. Please try again."
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
    assert dones[0]["data"]["suggestions"] == ["s1", "s2", "s3"]


@pytest.mark.asyncio
async def test_paused_interrupt_content_is_the_question_not_the_echoed_input(
    real_mode, monkeypatch
):
    """Regression: when planner_ask_node pauses on interrupt() without ever
    reaching its own return, `messages` still ends at the user's own input
    (nothing has been appended yet this turn) — the done event's content
    must come from the interrupt payload's question text, not from
    `messages[-1]`, or the user sees their own message echoed back."""
    graph = _FakeGraph(
        chunks=[],  # planner_ask_node produces no message chunks while paused
        state_values={"messages": [HumanMessage(content="help me plan my savings")]},
        interrupts=(
            SimpleNamespace(
                value={"question_id": "income_stability", "text": "Is your income stable?"}
            ),
        ),
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request(message="help me plan my savings")))
    dones = [e for e in events if e["event"] == "done"]
    tokens = [e["data"] for e in events if e["event"] == "token"]

    assert len(dones) == 1
    assert dones[0]["data"]["content"] == "Is your income stable?"
    assert dones[0]["data"]["content"] != "help me plan my savings"
    assert tokens == ["Is your income stable?"]


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
    assert data["suggestions"] == ["s1", "s2", "s3"]
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
            "messages": [HumanMessage(content="hi")],
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

        # --- Part B: multi-turn planner routing pauses on interrupt() and
        # resumes via Command(resume=...) (service.py's actual mechanism —
        # see the snapshot.interrupts branch in stream_chat), capturing and
        # validating the answer rather than losing it.
        import uuid as uuid_module

        from langgraph.types import Command

        # derive_planner_context never raises (see context.py), but a real
        # DNS lookup against conftest's fake AI_SERVICE_BACKEND_DB__HOST
        # would otherwise slow this test down waiting to time out — fail
        # fast instead, exercising the same neutral-context fallback path.
        async def _failing_get_backend_session():
            raise RuntimeError("no real backend DB in this test")
            yield  # pragma: no cover - unreachable, keeps this an async generator

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr("app.backend_db.get_backend_session", _failing_get_backend_session)
        try:
            config_b = {"configurable": {"thread_id": "conv-t15-planner"}}

            state_first = {
                "messages": [HumanMessage(content="help me budget")],
                "user_id": uuid_module.uuid4(),
                "user_context": {},
                "stage": "",
                "intent": "",
                "planner_answers": {},
                "questions_asked": 0,
                "last_question_id": None,
                "planner_validation_attempts": 0,
                "planner_context": None,
                "pending_answer": None,
                "pending_validation_reason": None,
                "message_references": [],
                "widget": None,
            }
            await graph.ainvoke(state_first, config_b)
            snap1 = await graph.aget_state(config_b)
            # stage/questions_asked only update once planner_ask_node's
            # interrupt() actually resumes — before that, the graph is
            # simply paused, which is the thing to assert here.
            assert snap1.interrupts, "expected the planner to pause asking its first question"

            # The first question is income_stability (enum: consistent/
            # variable) — answer it validly so this asserts advancement,
            # not app/features/plan/service.py's reprompt-on-invalid path
            # (covered separately in test_planner_integration.py).
            await graph.ainvoke(Command(resume="consistent"), config_b)
            snap2 = await graph.aget_state(config_b)

            # The answer was captured and validated (not lost) — either the
            # questionnaire moved on to another question (paused again) or,
            # if that was the last one, completed outright.
            assert snap2.values.get("planner_answers", {}).get("income_stability") == "consistent"
            assert snap2.values.get("questions_asked", 0) >= 1
            assert snap2.interrupts or snap2.values.get("stage") == "plan_complete"
        finally:
            monkeypatch.undo()
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_spending_breakdown_widget_serializes_into_done(real_mode, monkeypatch):
    """The analysis widgets ride the same generic slot as the two original
    ones — nothing in the SSE layer knows their type."""
    from app.features.chat.schemas import SpendingBreakdownWidget

    widget = SpendingBreakdownWidget.model_validate(
        {
            "type": "spending_breakdown",
            "payload": {
                "currency": "EGP",
                "month": "July 2026",
                "total": 1000.0,
                "categories": [
                    {"name": "housing", "amount": 750.0, "pct": 75.0},
                    {"name": "groceries", "amount": 250.0, "pct": 25.0},
                ],
            },
        }
    )
    graph = _FakeGraph(
        chunks=[("Housing was your biggest expense.", "analysis")],
        state_values={
            "messages": [type("M", (), {"content": "Housing was your biggest expense."})()],
            "widget": widget,
            "message_references": [],
        },
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request(message="where did my money go?")))
    dones = [e for e in events if e["event"] == "done"]

    assert len(dones) == 1
    data = dones[0]["data"]
    assert data["widget"]["type"] == "spending_breakdown"
    payload = data["widget"]["payload"]
    assert payload["currency"] == "EGP"
    assert payload["month"] == "July 2026"
    assert [c["name"] for c in payload["categories"]] == ["housing", "groceries"]
    assert sum(c["pct"] for c in payload["categories"]) == pytest.approx(100.0)
    # Analysis is the first node to emit a widget AND references together.
    assert data["references"] == []
    assert "id" not in data


@pytest.mark.asyncio
async def test_transactions_list_widget_serializes_dates_as_iso(real_mode, monkeypatch):
    """`date` must reach the wire as a plain ISO date string — the frontend
    parses it, and there is no time component to invent."""
    from app.features.chat.schemas import TransactionsListWidget

    widget = TransactionsListWidget.model_validate(
        {
            "type": "transactions_list",
            "payload": {
                "currency": "EGP",
                "transactions": [
                    {
                        "id": "b3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
                        "title": "Carrefour",
                        "category": "groceries",
                        "type": "expense",
                        "amount": 340.25,
                        "date": "2026-07-14",
                    }
                ],
            },
        }
    )
    graph = _FakeGraph(
        chunks=[("Here are your recent transactions.", "analysis")],
        state_values={
            "messages": [type("M", (), {"content": "Here are your recent transactions."})()],
            "widget": widget,
            "message_references": [],
        },
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request(message="show my transactions")))
    data = [e for e in events if e["event"] == "done"][0]["data"]

    row = data["widget"]["payload"]["transactions"][0]
    assert row["date"] == "2026-07-14"
    assert row["type"] == "expense"
    assert row["id"] == "b3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


# --- tool_call events: best-effort thinking indicator for the analysis node --


@pytest.mark.asyncio
async def test_tool_call_started_and_completed_emitted_before_final_token(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[
            (
                AIMessage(
                    content="",
                    tool_calls=[{"name": "get_transactions", "args": {}, "id": "call_1"}],
                ),
                "analysis",
            ),
            (
                ToolMessage(content='{"count": 3}', tool_call_id="call_1", name="get_transactions"),
                "analysis",
            ),
            ("You spent 100 EGP.", "analysis"),
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    tool_calls = [e for e in events if e["event"] == "tool_call"]
    tokens = [e for e in events if e["event"] == "token"]

    assert tool_calls == [
        {
            "event": "tool_call",
            "data": {"call_id": "call_1", "tool": "get_transactions", "status": "started"},
        },
        {
            "event": "tool_call",
            "data": {"call_id": "call_1", "tool": "get_transactions", "status": "completed"},
        },
    ]
    # Thinking events precede the reply, not interleaved after it.
    assert events.index(tool_calls[-1]) < events.index(tokens[0])


@pytest.mark.asyncio
async def test_tool_call_dedup_when_tool_calls_repeat_across_chunks(real_mode, monkeypatch):
    """A provider may re-expose the same populated tool_calls entry across more
    than one streamed chunk of the same turn — only one `started` must reach
    the client, not one per chunk."""
    same_call = AIMessage(
        content="", tool_calls=[{"name": "compute_aggregate", "args": {}, "id": "call_1"}]
    )
    graph = _FakeGraph(
        chunks=[(same_call, "analysis"), (same_call, "analysis")],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    started = [e for e in events if e["event"] == "tool_call" and e["data"]["status"] == "started"]

    assert len(started) == 1


@pytest.mark.asyncio
async def test_two_simultaneous_tool_calls_are_matched_by_call_id_not_order(real_mode, monkeypatch):
    """The analysis loop can hand back more than one tool call in a single
    AIMessage (`for call in tool_calls:`). Completion must pair with the
    call_id that actually finished, not "whichever started most recently" —
    here B's tool result arrives before A's, which a last-started heuristic
    would get wrong."""
    graph = _FakeGraph(
        chunks=[
            (
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "get_transactions", "args": {}, "id": "call_A"},
                        {"name": "compute_aggregate", "args": {}, "id": "call_B"},
                    ],
                ),
                "analysis",
            ),
            # B's result arrives first, out of call order.
            (
                ToolMessage(content="{}", tool_call_id="call_B", name="compute_aggregate"),
                "analysis",
            ),
            (ToolMessage(content="{}", tool_call_id="call_A", name="get_transactions"), "analysis"),
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    completed = [
        e["data"]
        for e in events
        if e["event"] == "tool_call" and e["data"]["status"] == "completed"
    ]

    assert completed == [
        {"call_id": "call_B", "tool": "compute_aggregate", "status": "completed"},
        {"call_id": "call_A", "tool": "get_transactions", "status": "completed"},
    ]


@pytest.mark.asyncio
async def test_tool_message_without_name_emits_no_event(real_mode, monkeypatch):
    """Defensive: a ToolMessage that somehow lacks `.name` (e.g. constructed by
    future code that doesn't set it) is silently skipped rather than emitting
    a malformed event — this is best-effort/informational, never required."""
    graph = _FakeGraph(
        chunks=[(ToolMessage(content="{}", tool_call_id="call_1"), "analysis")],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    assert [e for e in events if e["event"] == "tool_call"] == []


# --- agent_selected events: which specialist Maestro chose -------------------


def test_route_name_by_graph_node_excludes_clarify_and_refused():
    """Direct contract test: exactly the 5 real specialists are mapped, so
    `clarify`/`refused` — which delegate to no specialist — resolve to None
    with no separate exclusion list to maintain."""
    from app.features.chat.service import _ROUTE_NAME_BY_GRAPH_NODE

    assert len(_ROUTE_NAME_BY_GRAPH_NODE) == 5
    assert "clarify" not in _ROUTE_NAME_BY_GRAPH_NODE
    assert "refused" not in _ROUTE_NAME_BY_GRAPH_NODE
    assert _ROUTE_NAME_BY_GRAPH_NODE["analysis"] == "analysis"
    assert _ROUTE_NAME_BY_GRAPH_NODE["planner_ask"] == "planning"
    assert _ROUTE_NAME_BY_GRAPH_NODE["investment_plan"] == "investment_planning"
    assert _ROUTE_NAME_BY_GRAPH_NODE["recommendation"] == "recommendation"
    assert _ROUTE_NAME_BY_GRAPH_NODE["general"] == "general"


@pytest.mark.asyncio
async def test_agent_selected_precedes_first_token(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[("You ", "analysis"), ("spent 100 EGP.", "analysis")],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]
    tokens = [e for e in events if e["event"] == "token"]

    assert agent_selected == [{"event": "agent_selected", "data": {"agent": "analysis"}}]
    assert events.index(agent_selected[0]) < events.index(tokens[0])


@pytest.mark.asyncio
async def test_agent_selected_precedes_first_tool_call(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[
            (
                AIMessage(
                    content="",
                    tool_calls=[{"name": "get_transactions", "args": {}, "id": "call_1"}],
                ),
                "analysis",
            ),
            ("done", "analysis"),
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]
    tool_calls = [e for e in events if e["event"] == "tool_call"]

    assert agent_selected == [{"event": "agent_selected", "data": {"agent": "analysis"}}]
    assert events.index(agent_selected[0]) < events.index(tool_calls[0])


@pytest.mark.asyncio
async def test_agent_selected_not_duplicated_across_multiple_chunks(real_mode, monkeypatch):
    graph = _FakeGraph(
        chunks=[("part1 ", "general"), ("part2 ", "general"), ("part3", "general")],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]

    assert len(agent_selected) == 1


@pytest.mark.asyncio
async def test_agent_selected_via_interrupt_fallback_on_fresh_planning_turn(real_mode, monkeypatch):
    """Regression for the LangGraph interrupt() gap: a fresh (non-resumed)
    planner_ask turn calls interrupt() before any `return`, which LangGraph
    intercepts as a control-flow exception — zero message chunks are ever
    emitted for that invocation, so the primary detection path never fires.
    `intent` (the same state key graph.py's _route_intent() reads to route)
    must still yield the agent_selected event, via the fallback, before the
    interrupt's own question text is emitted as a token."""
    graph = _FakeGraph(
        chunks=[],  # planner_ask_node produces no message chunks while paused
        state_values={"messages": [], "intent": "planning"},
        interrupts=(
            SimpleNamespace(
                value={"question_id": "income_stability", "text": "Is your income stable?"}
            ),
        ),
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request(message="help me plan a budget")))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]
    tokens = [e for e in events if e["event"] == "token"]

    assert agent_selected == [{"event": "agent_selected", "data": {"agent": "planning"}}]
    assert events.index(agent_selected[0]) < events.index(tokens[0])


@pytest.mark.asyncio
async def test_agent_selected_fallback_skipped_when_primary_path_already_fired(
    real_mode, monkeypatch
):
    """A resumed Command(resume=...) turn that produces genuine AIMessage
    output before pausing again on the next question fires the primary
    path once; the fallback must not fire a second time for the same
    turn."""
    graph = _FakeGraph(
        chunks=[("Got it, growth it is.", "planner_ask")],
        state_values={"messages": [], "intent": "planning"},
        interrupts=(
            SimpleNamespace(
                value={"question_id": "next_question", "text": "How much do you save monthly?"}
            ),
        ),
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request(message="consistent")))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]

    assert len(agent_selected) == 1


@pytest.mark.asyncio
async def test_agent_selected_ignores_a_human_message_echo_relies_on_fallback(
    real_mode, monkeypatch
):
    """A turn whose only chunk is a HumanMessage — the shape
    investment_plan_node/planner_ask_node actually return on an ordinary
    interrupt-cycle continuation (echoing the user's own resumed answer,
    not a genuine reply) — must not announce that node as the turn's agent.
    It still gets a correct agent_selected, just via the interrupt fallback
    once the stream drains, since intent is unaffected by that echo."""
    graph = _FakeGraph(
        chunks=[(HumanMessage(content="5000 EGP"), "investment_plan")],
        state_values={"messages": [], "intent": "investment_planning"},
        interrupts=(
            SimpleNamespace(
                value={"question_id": "investment_scalars", "text": "What should this money do?"}
            ),
        ),
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request(message="5000 EGP")))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]

    assert agent_selected == [{"event": "agent_selected", "data": {"agent": "investment_planning"}}]


@pytest.mark.asyncio
async def test_agent_selected_reflects_the_specialist_that_escapes_a_leaf_node_hands_off_to(
    real_mode, monkeypatch
):
    """Regression for the investment-planner escape edge (graph.py's
    investment_plan -> maestro edge): a turn where investment_plan_node
    echoes the user's message (HumanMessage, no real answer) and then, in
    the SAME turn, hands off to a different leaf node that actually
    replies — agent_selected must reflect the node that really answered,
    not the leaf node the turn started in."""
    graph = _FakeGraph(
        chunks=[
            (HumanMessage(content="forget it, what are my transactions?"), "investment_plan"),
            ("You spent 100 EGP.", "analysis"),
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]

    assert agent_selected == [{"event": "agent_selected", "data": {"agent": "analysis"}}]


@pytest.mark.asyncio
async def test_internally_tagged_chunk_is_skipped_entirely(real_mode, monkeypatch):
    """The bug the previous test's fake-graph shape didn't actually catch
    live: investment_plan_node's internal answer-extraction call is itself
    an AIMessage chunk tagged "investment_plan" (LangGraph's
    stream_mode="messages" replays the raw output of *every* LLM call made
    anywhere in a graph run, not just calls whose surrounding node streams
    to the user) — so the AIMessage-only restriction alone doesn't exclude
    it. Tagged with INTERNAL_CALL_TAG (app.core.llm), it must be skipped
    entirely: no agent_selected, no token, no tool_call — as if it were
    never in the stream at all."""
    from app.core.llm import INTERNAL_CALL_TAG

    graph = _FakeGraph(
        chunks=[
            (
                AIMessage(content='{"is_escape":true,"confirmed_amount":null}'),
                "investment_plan",
                [INTERNAL_CALL_TAG],
            ),
            (HumanMessage(content="forget it, what are my transactions?"), "investment_plan"),
            ("You spent 100 EGP.", "analysis"),
        ],
        state_values={"messages": []},
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    agent_selected = [e for e in events if e["event"] == "agent_selected"]
    tokens = [e["data"] for e in events if e["event"] == "token"]

    assert agent_selected == [{"event": "agent_selected", "data": {"agent": "analysis"}}]
    assert "is_escape" not in "".join(tokens)


@pytest.mark.asyncio
async def test_agent_selected_absent_for_unroutable_fallback_intent(real_mode, monkeypatch):
    """Guards the fallback path: clarify/refuse turns leave `intent` unset (or
    stale/invalid), which must never resolve to a bogus agent_selected event."""
    graph = _FakeGraph(
        chunks=[],
        state_values={"messages": [], "intent": ""},
        interrupts=(SimpleNamespace(value={"question_id": "q", "text": "Could you clarify?"}),),
    )
    _install_fake_graph(monkeypatch, graph)

    events = _parse(await _collect(real_mode, _request()))
    assert [e for e in events if e["event"] == "agent_selected"] == []


@pytest.mark.asyncio
async def test_agent_selected_absent_for_clarify_and_refused_leaf_nodes(real_mode, monkeypatch):
    """clarify/refused delegate to no specialist — even though both are leaf
    nodes whose chunks are streamed as tokens, no agent_selected fires."""
    for node in ("clarify", "refused"):
        graph = _FakeGraph(
            chunks=[("Could you clarify what you mean?", node)],
            state_values={"messages": []},
        )
        _install_fake_graph(monkeypatch, graph)

        events = _parse(await _collect(real_mode, _request()))
        assert [e for e in events if e["event"] == "agent_selected"] == [], node
