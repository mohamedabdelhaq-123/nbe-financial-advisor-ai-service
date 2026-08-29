"""Integration tests for the investment planner's extraction-first scalar
phase and the escape-to-Maestro edge.

investment_plan_node uses LangGraph's interrupt() to pause mid-turn, so —
same as the budget planner (see test_planner_integration.py) — it can't be
unit-tested by calling it as a bare function once any scalar field is
missing. These tests run the actual compiled graph (InMemorySaver) and drive
multi-turn behavior via graph.ainvoke(state, config) then
graph.ainvoke(Command(resume=...), config), mirroring the mechanism already
verified live and used for real in chat/service.py.

Mock mode (settings.chat_model.use_mock, the test-suite default) drives
_mock_extract_investment_answers instead of a real model — see
agents/investment.py's docstring for why that path reuses _parse_answer's
existing per-field regex/alias matching rather than being inert offline.
"""

import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.features.chat.graph import build_graph

# Any of these is a legitimate reclassification target for a redirect-style
# escape message with no capability-specific keywords — mock mode's
# keyword classifier defaults to general, but this is deliberately broad
# rather than pinned to one exact route.
ROUTES_THAT_CAN_ANSWER_A_REDIRECT = {"general", "analysis", "recommendation", "planning"}


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
        "investment_answers": {},
        "investment_context": None,
        "investment_validation_attempts": 0,
        "investment_validation_reason": None,
        "message_references": [],
        "widget": None,
    }


@pytest.fixture(autouse=True)
def _no_real_backend_or_own_db(monkeypatch):
    """derive_investment_context's two sub-calls (transaction surplus via
    the backend DB, curated instruments via this service's own DB) both
    fail open to empty/default data (see context.py) — but without failing
    fast here, each test would otherwise pay for a real connection attempt
    against fake hostnames first."""

    async def _failing_get_backend_session():
        raise RuntimeError("no real backend DB in this test")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr("app.backend_db.get_backend_session", _failing_get_backend_session)

    async def _failing_list_curated_instruments():
        return []

    monkeypatch.setattr(
        "app.features.investment_plan.context.list_curated_instruments",
        _failing_list_curated_instruments,
    )


@pytest.mark.asyncio
async def test_scalar_phase_asks_one_consolidated_question_then_fills_from_one_message():
    graph, config = await _fresh_graph_and_config()

    await graph.ainvoke(_initial_state("I want to plan how to invest my extra money"), config)
    snap = await graph.aget_state(config)
    assert snap.interrupts, "expected the first consolidated question to pause on interrupt()"
    # One consolidated question, not one field at a time — every still-
    # missing field's own phrasing shows up in the same interrupt payload.
    question_text = snap.interrupts[0].value["text"]
    assert "How much price movement" in question_text  # risk
    assert "What should this money do for you" in question_text  # objective

    # One dense message supplies two fields at once (see test_agent.py's
    # collision note on why "moderate"/"quick" are avoided here).
    await graph.ainvoke(Command(resume="growth, long term"), config)
    snap = await graph.aget_state(config)
    assert snap.values["investment_answers"].get("objective") == "balanced_growth"
    assert snap.values["investment_answers"].get("horizon") == "long"
    assert snap.interrupts, "risk/liquidity/amount are still missing"


@pytest.mark.asyncio
async def test_scalar_phase_completes_and_moves_on_to_instruments():
    graph, config = await _fresh_graph_and_config()
    await graph.ainvoke(_initial_state("help me invest my remaining money"), config)

    # "aggressive"/"not soon" (rather than e.g. "moderate risk"/"not
    # important") deliberately avoid the risk/liquidity alias-set overlap
    # noted in test_agent.py — this regex-based mock approximation checks
    # each missing field independently, so a phrase like "moderate" that
    # both risk and liquidity recognize would get misattributed to
    # whichever field is checked first, a limitation specific to the mock
    # substitute, not the real extraction call.
    for answer in ["5000 EGP", "growth", "aggressive", "long term", "not soon"]:
        await graph.ainvoke(Command(resume=answer), config)

    snap = await graph.aget_state(config)
    answers = snap.values["investment_answers"]
    assert answers.get("confirmed_amount") == "5000.00"
    assert answers.get("objective") == "balanced_growth"
    assert answers.get("risk") == "high"
    assert answers.get("horizon") == "long"
    assert answers.get("liquidity") == "low"
    assert "instruments" not in answers
    # Empty catalogue in this test (see fixture) — still paused, now on the
    # instruments question specifically, proving the scalar phase handed
    # off cleanly to the unchanged deterministic instrument matcher.
    assert snap.interrupts
    assert snap.interrupts[0].value["question_id"] == "instruments"


@pytest.mark.asyncio
async def test_escaping_answers_the_interrupting_request_in_the_same_turn():
    graph, config = await _fresh_graph_and_config()
    await graph.ainvoke(_initial_state("help me invest my remaining money"), config)

    # Needs to satisfy two separate things at once: (a) contain one of
    # _mock_extract_investment_answers' own escape keywords ("forget"), so
    # the mock extraction actually flags is_escape rather than falling into
    # the ordinary "nothing matched" reprompt branch — "what are my
    # transactions" alone doesn't do that, it has no escape keyword; and
    # (b) contain unambiguous analysis vocabulary ("transactions") so
    # mock-mode's classifier matches a real route directly rather than
    # falling back to scanning conversation history (which still says
    # "invest" from the triggering message, and would reclassify straight
    # back into investment_planning — a mock-classifier quirk, not
    # something a real LLM would do).
    result = await graph.ainvoke(Command(resume="forget it, what are my transactions"), config)
    snap = await graph.aget_state(config)

    # Routed to a real specialist within the same turn — not stuck on the
    # investment questionnaire, not still paused waiting for a scalar
    # answer.
    assert snap.values.get("last_active_route") == "analysis"
    assert not snap.interrupts
    messages = result.get("messages") or snap.values.get("messages") or []
    assert messages, "expected the reclassified specialist to actually reply this turn"


@pytest.mark.asyncio
async def test_escaping_preserves_investment_answers_for_later():
    graph, config = await _fresh_graph_and_config()
    await graph.ainvoke(_initial_state("help me invest my remaining money"), config)
    await graph.ainvoke(Command(resume="5000 EGP"), config)

    snap = await graph.aget_state(config)
    assert snap.values["investment_answers"].get("confirmed_amount") == "5000.00"

    await graph.ainvoke(Command(resume="let's forget about this"), config)
    snap = await graph.aget_state(config)
    # PR 1's guard: escaping must not have wiped what was already answered.
    assert snap.values["investment_answers"].get("confirmed_amount") == "5000.00"

    # Coming back to investment planning later resumes, not restarts. Reuses
    # _initial_state's shape but threads investment_answers/_context forward
    # from the current checkpoint — mirroring what service.py's real
    # run_input construction already does for a fresh (non-resumed) turn on
    # an existing conversation (untouched by this PR); _initial_state alone
    # would explicitly reset investment_answers to {} the way a genuinely
    # new conversation should, which isn't what this step is testing.
    continuation = _initial_state("ok let's go back to planning that investment")
    continuation["investment_answers"] = dict(snap.values.get("investment_answers") or {})
    continuation["investment_context"] = snap.values.get("investment_context")
    await graph.ainvoke(continuation, config)
    snap = await graph.aget_state(config)
    assert snap.values["investment_answers"].get("confirmed_amount") == "5000.00"
    assert snap.interrupts, "expected to resume asking for whatever's still missing"
    # amount already known — its specific phrasing must not reappear (note
    # "How much" alone isn't a safe marker: the risk question also reads
    # "How much price movement are you comfortable with").
    assert "would you like to plan with" not in snap.interrupts[0].value["text"]


@pytest.mark.asyncio
async def test_escaping_also_works_at_the_instruments_selection_step():
    """The scalar phase isn't the only place an escape can arrive — a user
    can just as easily bail once asked to pick instruments. Regression test
    for a real gap: that step used to have no escape detection at all, so
    "forget about this" fell straight into _parse_answer's error path and
    just re-asked the same question instead of handing back to Maestro."""
    graph, config = await _fresh_graph_and_config()
    await graph.ainvoke(_initial_state("help me invest my remaining money"), config)
    for answer in ["5000 EGP", "growth", "aggressive", "long term", "not soon"]:
        await graph.ainvoke(Command(resume=answer), config)

    snap = await graph.aget_state(config)
    assert snap.interrupts[0].value["question_id"] == "instruments"

    result = await graph.ainvoke(Command(resume="forget it, what are my transactions"), config)
    snap = await graph.aget_state(config)

    assert snap.values.get("last_active_route") == "analysis"
    assert not snap.interrupts
    messages = result.get("messages") or snap.values.get("messages") or []
    assert messages, "expected the reclassified specialist to actually reply this turn"
    # Same PR 1 guard as the scalar-phase escape: nothing already answered
    # is discarded just because this turn bailed on the instruments step.
    assert snap.values["investment_answers"].get("confirmed_amount") == "5000.00"
    assert "instruments" not in snap.values["investment_answers"]


@pytest.mark.asyncio
async def test_three_unrecognized_replies_cancel_without_losing_the_running_budget():
    """MAX_VALIDATION_ATTEMPTS is now shared across the whole batch of
    missing scalar fields, not one specific field — three messages in a row
    that match none of them (and aren't an escape) still cancels the plan,
    same safety net as before."""
    graph, config = await _fresh_graph_and_config()
    await graph.ainvoke(_initial_state("help me invest my remaining money"), config)

    for _ in range(3):
        await graph.ainvoke(Command(resume="purple elephant"), config)

    snap = await graph.aget_state(config)
    assert snap.values.get("stage") == "investment_plan_cancelled"
    assert not snap.interrupts
