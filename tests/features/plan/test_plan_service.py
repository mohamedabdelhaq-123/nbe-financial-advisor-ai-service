"""US3 Unit tests: Budget plan service."""

import pytest

from app.features.plan.service import MAX_QUESTIONS, generate_plan, next_question


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
        user_context={"monthly_income": 5000},
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
