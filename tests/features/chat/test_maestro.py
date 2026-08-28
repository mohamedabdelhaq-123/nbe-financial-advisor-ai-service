"""Unit tests for Maestro's context-aware structured routing."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError
from structlog.testing import capture_logs

from app.core.config import settings
from app.features.chat.agents.maestro import (
    _normalise_decision,
    classify_intent,
    maestro_node,
)
from app.features.chat.routing import MaestroRoutingDecision
from app.features.chat.scope_guard import ScopeResult
from redteam.runners.fake_llm import install_fake_chat_model


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("how much did I spend on food last month", "analysis"),
        ("show me my transactions", "analysis"),
        ("help me budget for next month", "planning"),
        ("which credit card should I get", "recommendation"),
        ("what savings account is best", "recommendation"),
        ("help me invest my remaining money", "investment_planning"),
        ("check the latest gold price for an investment plan", "investment_planning"),
        ("hello there", "general"),
    ],
)
def test_mock_classifier_exercises_each_offline_graph_route(message: str, expected: str):
    assert classify_intent(message) == expected


def test_mock_classifier_uses_history_for_an_elliptical_followup():
    assert (
        classify_intent(
            "what about this month?",
            history="human: what did i spend on the most last month?",
        )
        == "analysis"
    )


def test_mock_classifier_prefers_latest_message_over_history():
    assert (
        classify_intent(
            "which credit card should I get?",
            history="human: what did i spend on the most last month?",
        )
        == "recommendation"
    )


def test_low_confidence_route_becomes_one_short_clarification(monkeypatch):
    monkeypatch.setattr(settings.maestro_routing, "minimum_confidence", 0.7)
    result = _normalise_decision(
        MaestroRoutingDecision(outcome="route", route="analysis", confidence=0.4)
    )
    assert result.outcome == "clarify"
    assert result.route is None
    assert result.clarification_question
    assert len(result.clarification_question) <= 180


def test_unknown_model_route_is_rejected_by_the_structured_schema():
    with pytest.raises(ValidationError):
        MaestroRoutingDecision(outcome="route", route="invented_agent", confidence=0.99)


def test_irrelevant_route_is_discarded_for_refuse_or_clarify_outcome():
    refused = MaestroRoutingDecision(outcome="refuse", route="general", confidence=0.99)
    clarified = MaestroRoutingDecision(
        outcome="clarify",
        route="analysis",
        confidence=0.8,
        clarification_question="Which period would you like to review?",
    )
    assert refused.route is None
    assert clarified.route is None


def test_clarification_with_internal_route_names_is_rewritten_for_users():
    result = _normalise_decision(
        MaestroRoutingDecision(
            outcome="clarify",
            route="general",
            confidence=0.8,
            clarification_question="Do you want analysis or recommendation?",
        )
    )
    assert "analysis" not in result.clarification_question.lower()
    assert "recommendation" not in result.clarification_question.lower()


@pytest.mark.asyncio
async def test_real_maestro_uses_validated_structured_output_for_a_long_message(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="route", route="analysis", confidence=0.94)
    calls = install_fake_chat_model(monkeypatch, structured_response=decision)
    long_message = (
        "I have been trying to understand my finances across the last few months. "
        "Please use my existing transactions to show where my spending increased, "
        "but do not start a new budget questionnaire yet."
    )

    result = await maestro_node(
        {
            "messages": [HumanMessage(content=long_message)],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
        }
    )

    assert result["intent"] == "analysis"
    assert result["routing_outcome"] == "route"
    assert result["routing_confidence"] == 0.94
    assert len(calls) == 1
    assert isinstance(calls[0][0], SystemMessage)
    assert isinstance(calls[0][1], HumanMessage)
    assert calls[0][1].content.endswith(long_message)


@pytest.mark.asyncio
async def test_real_maestro_routes_savings_account_request_to_recommendations(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="route", route="recommendation", confidence=0.98)
    calls = install_fake_chat_model(monkeypatch, structured_response=decision)

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="Which savings account should I choose?")],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
        }
    )

    assert result["intent"] == "recommendation"
    assert result["routing_outcome"] == "route"
    assert "savings account" in calls[0][1].content.lower()


@pytest.mark.asyncio
async def test_real_maestro_uses_its_configured_model_and_small_output_budget(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    monkeypatch.setattr(settings.maestro_routing, "model_name", "routing-model")
    monkeypatch.setattr(settings.maestro_routing, "max_output_tokens", 384)
    requested = {}

    class _StructuredModel:
        def with_structured_output(self, schema):
            requested["schema"] = schema
            return self

        async def ainvoke(self, messages):
            return MaestroRoutingDecision(
                outcome="route",
                route="recommendation",
                confidence=0.98,
            )

    def _fake_model_factory(**kwargs):
        requested.update(kwargs)
        return _StructuredModel()

    monkeypatch.setattr("app.core.llm.get_chat_model", _fake_model_factory)

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="Which savings account should I choose?")],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
        }
    )

    assert result["intent"] == "recommendation"
    assert requested == {
        "max_tokens": 384,
        "disable_reasoning": True,
        "model_name": "routing-model",
        "schema": MaestroRoutingDecision,
    }


@pytest.mark.asyncio
async def test_real_maestro_sends_recent_context_for_a_short_answer(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="route", route="investment_planning", confidence=0.96)
    calls = install_fake_chat_model(monkeypatch, structured_response=decision)

    async def _fake_investment_context(state):
        return {"investment_context": {"instruments": []}, "investment_answers": {}}

    monkeypatch.setattr(
        "app.features.chat.agents.maestro._investment_context_update",
        _fake_investment_context,
    )

    result = await maestro_node(
        {
            "messages": [
                HumanMessage(content="How should I invest my remaining money?"),
                AIMessage(content="What is your main objective?"),
                HumanMessage(content="growth"),
            ],
            "stage": "",
            "questions_asked": 0,
            "intent": "general",
        }
    )

    assert result["intent"] == "investment_planning"
    assert "What is your main objective?" in calls[0][1].content
    assert calls[0][1].content.endswith("Latest user message: growth")


@pytest.mark.asyncio
async def test_active_investment_questionnaire_routes_growth_without_reclassification(monkeypatch):
    def _unexpected_model():
        raise AssertionError("active workflow answers must not be reclassified")

    monkeypatch.setattr("app.core.llm.get_chat_model", _unexpected_model)
    result = await maestro_node(
        {
            "messages": [HumanMessage(content="growth")],
            "stage": "investment_planning",
            "questions_asked": 0,
            "intent": "investment_planning",
        }
    )

    assert result["intent"] == "investment_planning"
    assert result["routing_outcome"] == "route"


@pytest.mark.asyncio
async def test_real_maestro_refuses_out_of_scope_without_routing_to_general(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="refuse", confidence=0.98)
    install_fake_chat_model(monkeypatch, structured_response=decision)

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="write me a cooking recipe")],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
        }
    )

    assert result["routing_outcome"] == "refuse"
    assert result["in_scope"] is False


@pytest.mark.asyncio
async def test_invalid_structured_result_fails_to_clarification_not_keywords(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    install_fake_chat_model(monkeypatch, structured_response={"route": "analysis"})

    with capture_logs() as logs:
        result = await maestro_node(
            {
                "messages": [HumanMessage(content="show spending")],
                "stage": "",
                "questions_asked": 0,
                "intent": "",
            }
        )

    assert result["routing_outcome"] == "clarify"
    assert result["intent"] == "general"
    assert any(entry["event"] == "maestro_routing_failed" for entry in logs)


@pytest.mark.asyncio
async def test_nli_shadow_is_observed_but_cannot_override_maestro(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", True)
    monkeypatch.setattr(settings.nli_shadow, "enabled", True)

    async def _shadow_disagrees(text):
        return ScopeResult(in_scope=False, top_label="other", score=0.91)

    monkeypatch.setattr("app.features.chat.scope_guard.check_scope", _shadow_disagrees)

    with capture_logs() as logs:
        result = await maestro_node(
            {
                "messages": [HumanMessage(content="hello there")],
                "stage": "",
                "questions_asked": 0,
                "intent": "",
            }
        )

    assert result["routing_outcome"] == "route"
    assert result["intent"] == "general"
    comparison = next(entry for entry in logs if entry["event"] == "nli_shadow_comparison")
    assert comparison["agreement"] is False
    assert comparison["nli_in_scope"] is False


@pytest.mark.asyncio
async def test_slow_nli_shadow_does_not_delay_maestro_reply(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", True)
    monkeypatch.setattr(settings.nli_shadow, "enabled", True)
    release_shadow = asyncio.Event()
    shadow_finished = asyncio.Event()

    async def _slow_shadow(text):
        await release_shadow.wait()
        shadow_finished.set()
        return ScopeResult(in_scope=True, top_label="finance", score=0.8)

    monkeypatch.setattr("app.features.chat.scope_guard.check_scope", _slow_shadow)

    result = await asyncio.wait_for(
        maestro_node(
            {
                "messages": [HumanMessage(content="hello there")],
                "stage": "",
                "questions_asked": 0,
                "intent": "",
            }
        ),
        timeout=0.1,
    )

    assert result["intent"] == "general"
    assert shadow_finished.is_set() is False
    release_shadow.set()
    await asyncio.wait_for(shadow_finished.wait(), timeout=1)


@pytest.mark.asyncio
async def test_cancelling_maestro_also_cancels_optional_nli_shadow(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    monkeypatch.setattr(settings.nli_shadow, "enabled", True)
    shadow_started = asyncio.Event()
    shadow_cancelled = asyncio.Event()

    async def _blocking_shadow(text):
        shadow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            shadow_cancelled.set()
            raise

    class _BlockingModel:
        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, messages):
            await asyncio.Event().wait()

    monkeypatch.setattr("app.features.chat.scope_guard.check_scope", _blocking_shadow)
    monkeypatch.setattr("app.core.llm.get_chat_model", lambda *args, **kwargs: _BlockingModel())

    routing_task = asyncio.create_task(
        maestro_node(
            {
                "messages": [HumanMessage(content="show my spending")],
                "stage": "",
                "questions_asked": 0,
                "intent": "",
            }
        )
    )
    await asyncio.wait_for(shadow_started.wait(), timeout=1)
    routing_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await routing_task
    await asyncio.wait_for(shadow_cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_maestro_node_uses_history_for_elliptical_followup_in_mock_mode():
    state = {
        "messages": [
            HumanMessage(content="what did i spend on the most last month?"),
            AIMessage(content="I don't have that data yet. Backend is unavailable."),
            HumanMessage(content="what about this month?"),
        ],
        "stage": "",
        "questions_asked": 0,
        "intent": "",
    }
    result = await maestro_node(state)
    assert result["intent"] == "analysis"


@pytest.mark.asyncio
async def test_completed_investment_plan_accepts_catalogue_selection_change():
    instrument_id = uuid.uuid4()
    state = {
        "messages": [HumanMessage(content="EGX30 Index ETF")],
        "stage": "investment_plan_complete",
        "questions_asked": 0,
        "investment_context": {
            "instruments": [
                {
                    "id": str(instrument_id),
                    "product_id": str(uuid.uuid4()),
                    "code": "egx30-index-etf",
                    "display_name": "EGX30 Index ETF",
                    "asset_class": "fund",
                    "provider_symbol": "EGX30ETF_MARKET_PRICE",
                    "price_type": "market_price",
                    "price_currency": "EGP",
                    "unit": "fund_unit",
                    "minimum_increment": str(Decimal("1")),
                    "fractional_units_supported": False,
                    "max_quote_age_seconds": 259200,
                    "aliases": ["fund", "etf", "egx30"],
                    "objectives": ["balanced_growth"],
                    "risk_level": "high",
                    "horizons": ["long"],
                    "liquidity_level": "high",
                }
            ]
        },
        "investment_answers": {
            "confirmed_amount": "1200.00",
            "objective": "balanced_growth",
            "risk": "moderate",
            "horizon": "medium",
            "liquidity": "medium",
            "instruments": [str(uuid.uuid4())],
        },
    }

    result = await maestro_node(state)

    assert result["intent"] == "investment_planning"
    assert result["stage"] == "investment_planning"
    assert result["investment_answers"]["instruments"] == [str(instrument_id)]
    assert result["investment_answers"]["confirmed_amount"] == "1200.00"
    assert result["last_active_route"] == "investment_planning"


@pytest.mark.parametrize(
    "message",
    [
        "how much should i save each month?",
        "how much can i save?",
        "what if i save per month more than usual",
        "show me a savings projection",
    ],
)
def test_savings_projection_questions_route_to_analysis_in_mock_mode(message):
    assert classify_intent(message) == "analysis"


@pytest.mark.parametrize(
    "message",
    ["which savings account is best?", "recommend a savings account"],
)
def test_savings_account_questions_route_to_recommendation_in_mock_mode(message):
    assert classify_intent(message) == "recommendation"


# --- last_active_route: visibility into the last capability that routed -----


@pytest.mark.asyncio
async def test_route_decision_sets_last_active_route(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="route", route="analysis", confidence=0.94)
    install_fake_chat_model(monkeypatch, structured_response=decision)

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="how much did I spend on food?")],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
        }
    )

    assert result["last_active_route"] == "analysis"


@pytest.mark.asyncio
async def test_clarify_decision_does_not_set_last_active_route(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(
        outcome="clarify",
        confidence=0.5,
        clarification_question="Do you want to check spending or build a budget?",
    )
    install_fake_chat_model(monkeypatch, structured_response=decision)

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="help with money")],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
        }
    )

    assert result["routing_outcome"] == "clarify"
    assert "last_active_route" not in result


@pytest.mark.asyncio
async def test_refuse_decision_does_not_set_last_active_route(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="refuse", confidence=0.98)
    install_fake_chat_model(monkeypatch, structured_response=decision)

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="write me a cooking recipe")],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
        }
    )

    assert result["routing_outcome"] == "refuse"
    assert "last_active_route" not in result


@pytest.mark.asyncio
async def test_mid_planning_continuation_sets_last_active_route(monkeypatch):
    def _unexpected_model():
        raise AssertionError("active workflow answers must not be reclassified")

    monkeypatch.setattr("app.core.llm.get_chat_model", _unexpected_model)

    async def _fake_planner_context(state):
        return {}

    monkeypatch.setattr(
        "app.features.chat.agents.maestro._planner_context_update",
        _fake_planner_context,
    )

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="2500 EGP")],
            "stage": "planning",
            "questions_asked": 1,
            "intent": "planning",
            "planner_context": {"stub": True},
        }
    )

    assert result["last_active_route"] == "planning"


@pytest.mark.asyncio
async def test_active_investment_questionnaire_sets_last_active_route(monkeypatch):
    def _unexpected_model():
        raise AssertionError("active workflow answers must not be reclassified")

    monkeypatch.setattr("app.core.llm.get_chat_model", _unexpected_model)
    result = await maestro_node(
        {
            "messages": [HumanMessage(content="growth")],
            "stage": "investment_planning",
            "questions_asked": 0,
            "intent": "investment_planning",
        }
    )

    assert result["last_active_route"] == "investment_planning"


@pytest.mark.asyncio
async def test_real_maestro_receives_last_active_route_in_the_prompt(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="route", route="general", confidence=0.9)
    calls = install_fake_chat_model(monkeypatch, structured_response=decision)

    result = await maestro_node(
        {
            "messages": [HumanMessage(content="why did you choose those assets for me?")],
            "stage": "",
            "questions_asked": 0,
            "intent": "recommendation",
            "last_active_route": "recommendation",
        }
    )

    assert '"recommendation" capability' in calls[0][1].content
    assert result["last_active_route"] == "general"


@pytest.mark.asyncio
async def test_real_maestro_ignores_stale_last_active_route(monkeypatch):
    """A checkpoint from before this field existed, or a since-removed route
    name, degrades to no signal rather than a misleading prompt or a
    template render error (StrictUndefined would raise if the key were
    missing entirely from the render call, not merely None)."""
    monkeypatch.setattr(settings.chat_model, "use_mock", False)
    decision = MaestroRoutingDecision(outcome="route", route="general", confidence=0.9)
    calls = install_fake_chat_model(monkeypatch, structured_response=decision)

    await maestro_node(
        {
            "messages": [HumanMessage(content="hello")],
            "stage": "",
            "questions_asked": 0,
            "intent": "",
            "last_active_route": "deprecated_route",
        }
    )

    assert "previous turn" not in calls[0][1].content
