"""Context-aware Maestro orchestrator for scope and capability routing."""

import asyncio
from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.features.chat.routing import (
    DEFAULT_CLARIFICATION,
    ROUTES_BY_NAME,
    MaestroRoutingDecision,
    mock_routing_decision,
    route_catalogue,
)
from app.features.chat.state import ConversationState

logger = get_logger(__name__)
_shadow_comparison_tasks: set[asyncio.Task[None]] = set()


def classify_intent(message: str, history: str = "") -> str:
    """Backward-compatible deterministic helper for offline/mock callers only."""

    return mock_routing_decision(message, history).route or "general"


def _clarification_decision() -> MaestroRoutingDecision:
    return MaestroRoutingDecision(
        outcome="clarify",
        confidence=0.0,
        clarification_question=DEFAULT_CLARIFICATION,
    )


def _normalise_decision(decision: MaestroRoutingDecision) -> MaestroRoutingDecision:
    """Validate a model decision against the live route catalogue."""

    if decision.outcome != "route":
        if decision.outcome == "clarify":
            question = (decision.clarification_question or "").casefold()
            internal_terms = ("analysis", "recommendation", "investment_planning", "route")
            if any(term in question for term in internal_terms):
                return MaestroRoutingDecision(
                    outcome="clarify",
                    confidence=decision.confidence,
                    clarification_question=DEFAULT_CLARIFICATION,
                )
        return decision
    if decision.route not in ROUTES_BY_NAME:
        logger.warning("maestro_unknown_route", route=decision.route)
        return _clarification_decision()
    if decision.confidence < settings.maestro_routing.minimum_confidence:
        logger.info(
            "maestro_low_confidence",
            route=decision.route,
            confidence=decision.confidence,
        )
        return MaestroRoutingDecision(
            outcome="clarify",
            confidence=decision.confidence,
            clarification_question=DEFAULT_CLARIFICATION,
        )
    return decision


async def _log_shadow_comparison(
    shadow_task: asyncio.Task, decision: MaestroRoutingDecision
) -> None:
    """Record optional legacy NLI telemetry without delaying the chat turn."""

    try:
        shadow = await shadow_task
    except asyncio.CancelledError:
        return

    maestro_in_scope = decision.outcome != "refuse"
    logger.info(
        "nli_shadow_comparison",
        maestro_outcome=decision.outcome,
        maestro_route=decision.route,
        maestro_in_scope=maestro_in_scope,
        nli_in_scope=shadow.in_scope,
        nli_top_label=shadow.top_label,
        nli_score=shadow.score,
        agreement=maestro_in_scope == shadow.in_scope,
    )


def _continue_shadow_comparison(
    shadow_task: asyncio.Task, decision: MaestroRoutingDecision
) -> None:
    comparison_task = asyncio.create_task(_log_shadow_comparison(shadow_task, decision))
    _shadow_comparison_tasks.add(comparison_task)
    comparison_task.add_done_callback(_shadow_comparison_tasks.discard)


async def _decide_route(
    state: ConversationState, text: str, history: str
) -> MaestroRoutingDecision:
    """Make one scope + route decision and optionally compare legacy NLI."""

    shadow_task: asyncio.Task | None = None
    if settings.nli_shadow.enabled:
        from app.features.chat.scope_guard import build_scope_check_text, check_scope

        shadow_text = build_scope_check_text(
            state["messages"],
            last_intent=state.get("intent"),
        )
        shadow_task = asyncio.create_task(check_scope(shadow_text))

    try:
        if settings.chat_model.use_mock:
            decision = mock_routing_decision(text, history=history)
        else:
            try:
                from app.core.llm import get_chat_model
                from app.features.chat.prompts import (
                    get_maestro_routing_human_prompt,
                    get_maestro_routing_system_prompt,
                )

                # A stale/unknown value (older checkpoint predating this field,
                # or a since-removed route) degrades to no signal rather than
                # a misleading prompt or a template render error.
                previous_route = state.get("last_active_route")
                if previous_route not in ROUTES_BY_NAME:
                    previous_route = None

                system_prompt = get_maestro_routing_system_prompt().render(routes=route_catalogue())
                human_prompt = get_maestro_routing_human_prompt().render(
                    message=text,
                    history=history or None,
                    last_active_route=previous_route,
                )
                # Routing needs only a tiny JSON object. Bound output and turn
                # off optional model reasoning so a provider cannot spend a
                # long completion budget on this classification step.
                structured_llm = get_chat_model(
                    max_tokens=settings.maestro_routing.max_output_tokens,
                    disable_reasoning=True,
                    model_name=settings.maestro_routing.model_name or None,
                ).with_structured_output(MaestroRoutingDecision)
                raw_decision = await structured_llm.ainvoke(
                    [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
                )
                decision = (
                    raw_decision
                    if isinstance(raw_decision, MaestroRoutingDecision)
                    else MaestroRoutingDecision.model_validate(raw_decision)
                )
            except Exception:
                logger.exception("maestro_routing_failed")
                decision = _clarification_decision()

        decision = _normalise_decision(cast(MaestroRoutingDecision, decision))

        if shadow_task is not None:
            # Let an already-fast comparison finish in this event-loop turn so
            # its telemetry remains deterministic in tests. Slow hosted/local
            # NLI work continues in the background and never delays the reply.
            await asyncio.sleep(0)
            if shadow_task.done():
                await _log_shadow_comparison(shadow_task, decision)
            else:
                _continue_shadow_comparison(shadow_task, decision)

        return decision
    except asyncio.CancelledError:
        # The shadow check is independent telemetry. Do not leave it running
        # after a client disconnect or service shutdown cancels the real turn.
        if shadow_task is not None and not shadow_task.done():
            shadow_task.cancel()
        raise


def _decision_state(decision: MaestroRoutingDecision) -> dict:
    result = {
        "intent": decision.route or "general",
        "in_scope": decision.outcome != "refuse",
        "routing_outcome": decision.outcome,
        "routing_confidence": decision.confidence,
        "routing_clarification": decision.clarification_question,
    }
    if decision.outcome == "route":
        # Only set on an actual route — absent from a clarify/refuse turn's
        # returned dict, so LangGraph's partial-update merge leaves the
        # checkpointed value from before that turn untouched. See state.py's
        # last_active_route field comment for why.
        result["last_active_route"] = decision.route
    return result


async def _planner_context_update(state: ConversationState) -> dict:
    """Assembles planner_context once per session (Pipeline.md §3: Maestro
    assembles user context before delegating to a sub-agent) and caches it
    in state — never re-derives once set. Deriving it here rather than in
    planner_ask_node also sidesteps a real LangGraph interrupt() gotcha: a
    node that calls interrupt() re-executes from its own start on every
    resume, so anything before the interrupt() call would otherwise re-run
    (and re-hit the DB) on every single answer, not just once per session.
    Maestro doesn't run again during the interrupt loop at all, so this is
    the one place a single derivation actually sticks."""
    if state.get("planner_context") is not None:
        return {}
    from app.features.plan.context import derive_planner_context

    context = await derive_planner_context(state["user_id"])
    return {"planner_context": context}


async def _investment_context_update(state: ConversationState) -> dict:
    from app.features.investment_plan.context import derive_investment_context

    context = await derive_investment_context(state["user_id"])
    return {
        "investment_context": context.model_dump(mode="json"),
        "investment_answers": {},
        "investment_validation_attempts": 0,
        "investment_validation_reason": None,
    }


async def maestro_node(state: ConversationState) -> dict:
    # If we are already mid-planning (questions asked but plan not yet complete),
    # preserve the routing — the new message is an answer to the questionnaire,
    # not a fresh intent signal.
    if state.get("stage") == "planning" and state.get("questions_asked", 0) > 0:
        decision = MaestroRoutingDecision(outcome="route", route="planning", confidence=1.0)
        return {**_decision_state(decision), **await _planner_context_update(state)}
    if state.get("stage") == "investment_planning":
        decision = MaestroRoutingDecision(
            outcome="route", route="investment_planning", confidence=1.0
        )
        return _decision_state(decision)

    last_msg = state["messages"][-1] if state["messages"] else None
    text = ""
    if last_msg and hasattr(last_msg, "content") and isinstance(last_msg.content, str):
        text = last_msg.content

    # A completed scenario stays editable in normal conversation. Naming one
    # or more displayed catalogue options replaces only the selected
    # instruments; amount and suitability answers remain unchanged.
    if state.get("stage") == "investment_plan_complete":
        from app.features.chat.agents.investment import parse_instrument_selection

        selection = parse_instrument_selection(
            text,
            state.get("investment_context"),
            state.get("investment_answers"),
        )
        if selection:
            answers = dict(state.get("investment_answers") or {})
            answers["instruments"] = selection
            decision = MaestroRoutingDecision(
                outcome="route", route="investment_planning", confidence=1.0
            )
            return {
                **_decision_state(decision),
                "stage": "investment_planning",
                "investment_answers": answers,
                "investment_validation_attempts": 0,
                "investment_validation_reason": None,
            }

    from app.features.chat.summarize import format_turns

    history = format_turns(state["messages"][:-1], limit=4)

    decision = await _decide_route(state, text, history)
    result = _decision_state(decision)

    if decision.outcome != "route":
        return result

    if decision.route == "planning":
        was_first_turn = state.get("planner_context") is None
        extra = await _planner_context_update(state)
        if was_first_turn:
            from app.features.plan.service import extract_stated_goal

            stated_goal = await extract_stated_goal(text)
            if stated_goal:
                extra["stated_savings_goal"] = stated_goal
        return {**result, **extra}
    if decision.route == "investment_planning":
        return {**result, **await _investment_context_update(state)}
    return result
