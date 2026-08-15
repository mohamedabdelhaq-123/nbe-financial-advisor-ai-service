"""US3 Unit tests: Budget plan service."""

import pytest

from app.core.config import settings
from app.features.plan import service as plan_service
from app.features.plan.schemas import AnswerValidation, PlanQuestion
from app.features.plan.service import (
    MAX_QUESTIONS,
    QUESTIONS_BY_ID,
    extract_stated_goal,
    generate_plan,
    infer_answers_from_context,
    next_question,
    resolve_confirmation,
    validate_answer,
    validate_answer_deterministic,
    validate_answer_llm,
)


@pytest.mark.asyncio
async def test_next_question_returns_unanswered():
    answers = {"income_stability": "consistent"}
    result = await next_question({}, answers, 1)
    assert result is not None
    assert result.id != "income_stability"


@pytest.mark.asyncio
async def test_next_question_returns_none_when_cap_reached():
    result = await next_question({}, {}, MAX_QUESTIONS)
    assert result is None


@pytest.mark.asyncio
async def test_next_question_returns_none_when_all_answered():
    from app.features.plan.service import QUESTIONS

    answers = {q.id: "yes" for q in QUESTIONS}
    result = await next_question({}, answers, 0)
    assert result is None


@pytest.mark.asyncio
async def test_generate_plan_sums_to_100():
    allocations = await generate_plan(
        context={"avg_monthly_income": 5000},
        answers={"savings_goal": "yes", "fixed_expenses": "rent 1500"},
    )
    total = sum(a.percentage for a in allocations)
    assert total == 100


@pytest.mark.asyncio
async def test_generate_plan_deterministic_in_mock():
    a1 = await generate_plan({}, {"savings_goal": "no"})
    a2 = await generate_plan({}, {"savings_goal": "no"})
    assert [a.category for a in a1] == [a.category for a in a2]
    assert [a.percentage for a in a1] == [a.percentage for a in a2]


@pytest.mark.asyncio
async def test_generate_plan_categories_present():
    allocations = await generate_plan({}, {})
    categories = {a.category for a in allocations}
    assert "housing" in categories
    assert "savings" in categories


# --- validate_answer_deterministic --------------------------------------


def test_validate_answer_yes_no_accepts_variants():
    q = QUESTIONS_BY_ID["debt"]
    assert validate_answer_deterministic(q, "yeah").normalized_value == "yes"
    assert validate_answer_deterministic(q, "nope").normalized_value == "no"


def test_validate_answer_yes_no_rejects_other_text():
    q = QUESTIONS_BY_ID["debt"]
    result = validate_answer_deterministic(q, "maybe")
    assert result.valid is False
    assert result.reason


def test_validate_answer_enum_matches_loosely():
    q = QUESTIONS_BY_ID["risk_tolerance"]
    result = validate_answer_deterministic(q, "I'd say medium risk")
    assert result.valid is True
    assert result.normalized_value == "medium"


def test_validate_answer_enum_rejects_unknown_choice():
    q = QUESTIONS_BY_ID["risk_tolerance"]
    result = validate_answer_deterministic(q, "extreme")
    assert result.valid is False
    assert "low" in result.reason


def test_validate_answer_numeric_extracts_and_bounds_checks():
    q = QUESTIONS_BY_ID["dependents"]
    ok = validate_answer_deterministic(q, "I support 3 people")
    assert ok.valid is True
    assert ok.normalized_value == "3.0"

    too_high = validate_answer_deterministic(q, "50")
    assert too_high.valid is False


def test_validate_answer_numeric_rejects_no_digits():
    q = QUESTIONS_BY_ID["dependents"]
    result = validate_answer_deterministic(q, "a million")
    assert result.valid is False
    assert "number" in result.reason.lower()


def test_validate_answer_free_text_rejects_empty():
    q = QUESTIONS_BY_ID["fixed_expenses"]
    result = validate_answer_deterministic(q, "   ")
    assert result.valid is False


def test_validate_answer_free_text_defers_short_answers_to_llm():
    q = QUESTIONS_BY_ID["fixed_expenses"]
    assert validate_answer_deterministic(q, "rent") is None


def test_validate_answer_free_text_defers_long_content_to_llm_too():
    # Length alone doesn't distinguish a real answer from a non-answer —
    # a long reply still needs the LLM to judge intent, not just a
    # deterministic "long enough" rubber stamp. Regression coverage for a
    # real bug: "what do you mean?" (19 chars, all real words) was
    # previously auto-accepted as a valid answer by a length-only check.
    q = QUESTIONS_BY_ID["savings_goal"]
    assert validate_answer_deterministic(q, "rent and a car loan") is None
    assert validate_answer_deterministic(q, "what do you mean ?") is None


# --- validate_answer_llm (mock mode) -------------------------------------


@pytest.mark.asyncio
async def test_validate_answer_llm_mock_mode_accepts_any_nonempty_text():
    q = QUESTIONS_BY_ID["fixed_expenses"]
    result = await validate_answer_llm(q, "rent")
    assert result.valid is True
    assert result.normalized_value == "rent"


# --- validate_answer: composition, reason-enrichment for constrained kinds -


@pytest.mark.asyncio
async def test_validate_answer_valid_constrained_never_calls_llm(monkeypatch):
    def _fail_if_called(question, raw):
        raise AssertionError("validate_answer_llm must not run for an accepted answer")

    monkeypatch.setattr(plan_service, "validate_answer_llm", _fail_if_called)

    q = QUESTIONS_BY_ID["risk_tolerance"]
    result = await validate_answer(q, "medium", context={})
    assert result.valid is True
    assert result.normalized_value == "medium"


@pytest.mark.asyncio
async def test_validate_answer_mock_mode_keeps_canned_reason(monkeypatch):
    def _fail_if_called(question, raw):
        raise AssertionError("validate_answer_llm must not run in mock mode")

    monkeypatch.setattr(plan_service, "validate_answer_llm", _fail_if_called)
    monkeypatch.setattr(settings.chat_model, "use_mock", True)

    q = QUESTIONS_BY_ID["risk_tolerance"]
    result = await validate_answer(q, "what do you mean ?", context={})
    assert result.valid is False
    assert "low" in result.reason  # the canned "Please choose one of: ..." text


@pytest.mark.asyncio
async def test_validate_answer_real_mode_uses_llm_reason_on_rejection(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    async def _fake_llm(question, raw):
        return AnswerValidation(
            valid=False, reason="Risk tolerance means how much you're comfortable losing."
        )

    monkeypatch.setattr(plan_service, "validate_answer_llm", _fake_llm)

    q = QUESTIONS_BY_ID["risk_tolerance"]
    result = await validate_answer(q, "what do you mean ?", context={})
    assert result.valid is False
    assert result.reason == "Risk tolerance means how much you're comfortable losing."


@pytest.mark.asyncio
async def test_validate_answer_real_mode_never_lets_llm_override_validity(monkeypatch):
    # The core safety invariant: even if the enrichment call disagrees and
    # says "valid", a constrained-kind answer that failed deterministic
    # matching must stay rejected.
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    async def _fake_llm(question, raw):
        return AnswerValidation(valid=True, normalized_value=raw.strip())

    monkeypatch.setattr(plan_service, "validate_answer_llm", _fake_llm)

    q = QUESTIONS_BY_ID["risk_tolerance"]
    result = await validate_answer(q, "fsdaf", context={})
    assert result.valid is False
    assert "low" in result.reason  # original deterministic reason preserved


@pytest.mark.asyncio
async def test_validate_answer_real_mode_llm_failure_keeps_deterministic_result(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    async def _raising_llm(question, raw):
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr(plan_service, "validate_answer_llm", _raising_llm)

    q = QUESTIONS_BY_ID["risk_tolerance"]
    result = await validate_answer(q, "fsdaf", context={})
    assert result.valid is False
    assert "low" in result.reason


# --- infer_answers_from_context -------------------------------------------


def test_infer_answers_from_context_low_variance_infers_consistent():
    inferred = infer_answers_from_context({"income_variance_ratio": 0.05})
    assert inferred == {"income_stability": "consistent"}


def test_infer_answers_from_context_high_variance_infers_variable():
    inferred = infer_answers_from_context({"income_variance_ratio": 0.5})
    assert inferred == {"income_stability": "variable"}


def test_infer_answers_from_context_ambiguous_variance_does_not_infer():
    inferred = infer_answers_from_context({"income_variance_ratio": 0.2})
    assert inferred == {}


def test_infer_answers_from_context_no_signal_does_not_infer():
    assert infer_answers_from_context({}) == {}


def test_infer_answers_from_context_never_skips_fixed_expenses():
    # fixed_expenses only ever gets personalized wording, never a silent
    # skip — regardless of how strong the recurring-expense signal is.
    inferred = infer_answers_from_context({"avg_monthly_recurring_expense": 3000.0})
    assert "fixed_expenses" not in inferred


@pytest.mark.asyncio
async def test_next_question_personalizes_income_stability_question():
    context = {"avg_monthly_income": 5000.0, "currency": "EGP"}
    result = await next_question(context, {}, 0)
    assert result is not None
    assert result.id == "income_stability"
    assert "5000" in result.text


def test_plan_question_schema_defaults_to_free_text():
    q = PlanQuestion(id="custom", text="custom question")
    assert q.kind == "free_text"


# --- _personalize: dependents / savings_goal branches ----------------------


@pytest.mark.asyncio
async def test_next_question_personalizes_dependents_from_context():
    answers = {"income_stability": "consistent", "fixed_expenses": "rent"}
    context = {"dependents_count": 2}
    result = await next_question(context, answers, 2)
    assert result is not None
    assert result.id == "savings_goal"  # dependents comes after savings_goal in order


@pytest.mark.asyncio
async def test_next_question_personalizes_dependents_question_text():
    answers = {"income_stability": "x", "fixed_expenses": "x", "savings_goal": "x"}
    context = {"dependents_count": 2}
    result = await next_question(context, answers, 3)
    assert result is not None
    assert result.id == "dependents"
    assert "2" in result.text


@pytest.mark.asyncio
async def test_next_question_personalizes_savings_goal_from_context():
    answers = {"income_stability": "x", "fixed_expenses": "x"}
    context = {
        "savings_goal_name": "a house deposit",
        "savings_goal_target_amount": 100000.0,
        "savings_goal_timeline_months": 24,
        "currency": "EGP",
    }
    result = await next_question(context, answers, 2)
    assert result is not None
    assert result.id == "savings_goal"
    assert "a house deposit" in result.text
    assert "100000" in result.text
    assert "24" in result.text


@pytest.mark.asyncio
async def test_next_question_dependents_unpersonalized_without_context():
    answers = {"income_stability": "x", "fixed_expenses": "x", "savings_goal": "x"}
    result = await next_question({}, answers, 3)
    assert result is not None
    assert result.id == "dependents"
    assert result.text == QUESTIONS_BY_ID["dependents"].text


# --- resolve_confirmation ---------------------------------------------------


def test_resolve_confirmation_yes_resolves_dependents_from_context():
    context = {"dependents_count": 3}
    result = resolve_confirmation("dependents", "yes", context)
    assert result is not None
    assert result.valid is True
    assert result.normalized_value == "3"


def test_resolve_confirmation_yes_resolves_savings_goal_from_context():
    context = {
        "savings_goal_name": "a bike",
        "savings_goal_target_amount": 5000.0,
        "savings_goal_timeline_months": 6,
    }
    result = resolve_confirmation("savings_goal", "yep", context)
    assert result is not None
    assert result.valid is True
    assert "a bike" in result.normalized_value


def test_resolve_confirmation_correction_is_not_intercepted():
    # A real correction, not a bare confirmation — must fall through to
    # normal validation instead of being resolved from stale context.
    context = {"dependents_count": 3}
    assert resolve_confirmation("dependents", "actually 4 now", context) is None


def test_resolve_confirmation_no_context_value_returns_none():
    assert resolve_confirmation("dependents", "yes", {}) is None
    assert resolve_confirmation("savings_goal", "yes", {}) is None


def test_resolve_confirmation_unconfirmable_question_returns_none():
    assert resolve_confirmation("risk_tolerance", "yes", {"dependents_count": 3}) is None


# --- extract_stated_goal (mock mode) ----------------------------------------


@pytest.mark.asyncio
async def test_extract_stated_goal_mock_mode_returns_none():
    # Mock mode never calls the real LLM — matches validate_answer_llm's
    # offline-deterministic behavior. The feature is simply inert in tests.
    assert await extract_stated_goal("help me plan for a bike") is None
