"""Integration tests for the planner's interrupt-based ask/validate loop.

planner_ask_node uses LangGraph's interrupt() to pause mid-turn, so it can
no longer be unit-tested by calling it as a bare function — interrupt()
requires a compiled graph running under a checkpointer. These tests run the
actual compiled graph (InMemorySaver) and drive multi-turn behavior via
graph.ainvoke(state, config) then graph.ainvoke(Command(resume=...), config),
mirroring the exact mechanism verified live against LangGraph 1.2.9 during
this feature's planning session and used for real in chat/service.py.
"""

import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.features.chat.graph import build_graph
from app.features.chat.schemas import AllocationSliderWidget

# Deterministically valid answers for each of the 7 topics in order, per
# app/features/plan/service.py's QUESTIONS kinds.
_VALID_ANSWERS_IN_ORDER = [
    "consistent",  # income_stability (enum)
    "rent and phone bill",  # fixed_expenses (free_text, len >= 6)
    "5000 for emergency fund",  # savings_goal (free_text, len >= 6)
    "2",  # dependents (numeric)
    "medium",  # risk_tolerance (enum)
    "no",  # debt (yes_no)
    "moderate",  # lifestyle (enum)
]


async def _fresh_graph_and_config():
    graph = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return graph, config


def _initial_state(message: str) -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "user_id": uuid.uuid4(),
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


@pytest.fixture(autouse=True)
def _no_real_backend_db(monkeypatch):
    """derive_planner_context never raises, but without this every test
    would otherwise pay for a real (fake-hostname) DB connection attempt."""

    async def _failing_get_backend_session():
        raise RuntimeError("no real backend DB in this test")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr("app.backend_db.get_backend_session", _failing_get_backend_session)


@pytest.mark.asyncio
async def test_full_questionnaire_completes_with_valid_plan():
    graph, config = await _fresh_graph_and_config()

    await graph.ainvoke(_initial_state("help me budget"), config)
    snap = await graph.aget_state(config)
    assert snap.interrupts, "expected the first question to pause on interrupt()"

    for answer in _VALID_ANSWERS_IN_ORDER:
        await graph.ainvoke(Command(resume=answer), config)
        snap = await graph.aget_state(config)

    assert not snap.interrupts, "questionnaire should be complete, not paused"
    assert snap.values.get("stage") == "plan_complete"
    assert snap.values.get("questions_asked") == 7

    messages = snap.values.get("messages") or []
    assert messages, "expected a final reply message"
    last = messages[-1]
    assert "budget" in last.content.lower() or "plan" in last.content.lower()

    widget = snap.values.get("widget")
    assert isinstance(widget, AllocationSliderWidget)
    total = sum(a.percentage for a in widget.payload.allocations)
    assert total == 100


@pytest.mark.asyncio
async def test_invalid_numeric_answer_is_reprompted_not_advanced():
    graph, config = await _fresh_graph_and_config()

    await graph.ainvoke(_initial_state("help me budget"), config)
    # Answer the first two questions validly to reach "dependents" (numeric).
    await graph.ainvoke(Command(resume=_VALID_ANSWERS_IN_ORDER[0]), config)
    await graph.ainvoke(Command(resume=_VALID_ANSWERS_IN_ORDER[1]), config)
    await graph.ainvoke(Command(resume=_VALID_ANSWERS_IN_ORDER[2]), config)
    snap = await graph.aget_state(config)
    questions_asked_before = snap.values.get("questions_asked")
    # last_question_id lags one step behind while paused — it names the
    # question whose answer was just validated (savings_goal), not the one
    # currently pending. The currently-pending question is only visible via
    # the live interrupt payload until its own answer comes back in.
    assert snap.interrupts[0].value["question_id"] == "dependents"

    await graph.ainvoke(Command(resume="a million"), config)
    snap = await graph.aget_state(config)

    assert snap.interrupts, "expected a reprompt, not advancement"
    assert snap.values.get("questions_asked") == questions_asked_before
    assert snap.values.get("planner_validation_attempts") == 1
    assert "dependents" not in snap.values.get("planner_answers", {})
    reprompt_text = snap.interrupts[0].value["text"]
    assert "number" in reprompt_text.lower()


@pytest.mark.asyncio
async def test_three_invalid_answers_fall_back_to_accept_as_is():
    graph, config = await _fresh_graph_and_config()

    await graph.ainvoke(_initial_state("help me budget"), config)
    await graph.ainvoke(Command(resume=_VALID_ANSWERS_IN_ORDER[0]), config)
    await graph.ainvoke(Command(resume=_VALID_ANSWERS_IN_ORDER[1]), config)
    await graph.ainvoke(Command(resume=_VALID_ANSWERS_IN_ORDER[2]), config)

    await graph.ainvoke(Command(resume="a million"), config)
    await graph.ainvoke(Command(resume="loads"), config)
    snap = await graph.aget_state(config)
    assert snap.values.get("planner_validation_attempts") == 2

    await graph.ainvoke(Command(resume="still not a number"), config)
    snap = await graph.aget_state(config)

    # Retry cap hit — accepted as-is rather than trapping the user forever.
    assert snap.values.get("planner_validation_attempts") == 0
    assert snap.values.get("planner_answers", {}).get("dependents") == "still not a number"
    # last_question_id names the question just force-accepted (dependents);
    # the live interrupt shows the questionnaire actually moved on.
    assert snap.values.get("last_question_id") == "dependents"
    assert snap.interrupts
    assert snap.interrupts[0].value["question_id"] == "risk_tolerance"
    # The stale "Please answer with a number" reason from the dependents
    # retries must not leak into this unrelated question's prompt.
    reprompt_text = snap.interrupts[0].value["text"]
    assert "number" not in reprompt_text.lower()


@pytest.mark.asyncio
async def test_context_inferable_topic_is_never_asked(monkeypatch):
    async def _fake_derive_planner_context(user_id):
        return {
            "avg_monthly_income": 5000.0,
            "income_variance_ratio": 0.05,  # confidently "consistent"
            "months_of_income_data": 4,
            "avg_monthly_recurring_expense": None,
            "currency": "EGP",
        }

    monkeypatch.setattr(
        "app.features.plan.context.derive_planner_context", _fake_derive_planner_context
    )

    graph, config = await _fresh_graph_and_config()
    await graph.ainvoke(_initial_state("help me budget"), config)
    snap = await graph.aget_state(config)

    # income_stability was inferred, so the first real question asked is the
    # next topic in order instead. Nothing commits to planner_answers/
    # last_question_id until interrupt() actually resumes (it re-executes
    # the node from the top on resume) — but the interrupt's own payload is
    # visible immediately, which is enough to confirm the skip took effect.
    assert snap.interrupts, "expected a question to be asked"
    assert snap.interrupts[0].value["question_id"] == "fixed_expenses"

    # Resuming commits the merged inferred answer alongside the real one.
    await graph.ainvoke(Command(resume="rent and phone bill"), config)
    snap = await graph.aget_state(config)
    assert snap.values.get("planner_answers", {}).get("income_stability") == "consistent"
    assert snap.values.get("planner_answers", {}).get("fixed_expenses") == "rent and phone bill"


@pytest.mark.asyncio
async def test_bare_yes_resolves_to_known_context_value():
    # dependents (kind=numeric) would otherwise reject a bare "yes" outright
    # (no digits) — resolve_confirmation must intercept it first.
    graph, config = await _fresh_graph_and_config()
    state = _initial_state("help me budget")
    state["planner_context"] = {"dependents_count": 4}
    state["planner_answers"] = {
        "income_stability": "consistent",
        "fixed_expenses": "rent",
        "savings_goal": "a house",
    }
    state["questions_asked"] = 3

    await graph.ainvoke(state, config)
    snap = await graph.aget_state(config)
    assert snap.interrupts[0].value["question_id"] == "dependents"
    assert "4" in snap.interrupts[0].value["text"]

    await graph.ainvoke(Command(resume="yes"), config)
    snap = await graph.aget_state(config)
    assert snap.values.get("planner_answers", {}).get("dependents") == "4"


@pytest.mark.asyncio
async def test_opening_message_stated_goal_skips_savings_goal_question(monkeypatch):
    async def _fake_extract_stated_goal(message: str) -> str:
        return "a bike"

    monkeypatch.setattr("app.features.plan.service.extract_stated_goal", _fake_extract_stated_goal)

    graph, config = await _fresh_graph_and_config()
    await graph.ainvoke(_initial_state("help me plan for a bike"), config)
    snap = await graph.aget_state(config)
    assert snap.interrupts[0].value["question_id"] == "income_stability"

    # income_stability, then fixed_expenses — savings_goal must be skipped
    # entirely (already answered from the opening message), landing on
    # dependents next instead of asking savings_goal a third time.
    await graph.ainvoke(Command(resume="consistent"), config)
    await graph.ainvoke(Command(resume="rent and phone bill"), config)
    snap = await graph.aget_state(config)
    assert snap.interrupts[0].value["question_id"] == "dependents"
    assert snap.values.get("planner_answers", {}).get("savings_goal") == "a bike"
