"""US3 Unit tests: Budget plan service."""

import pytest

from app.features.plan.prompts import get_budget_allocation_prompt
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


# ---------------------------------------------------------------------------
# Prompt-template golden-string test (FR-005: byte-for-byte wording preservation)
# ---------------------------------------------------------------------------

_GOLDEN_BUDGET = (
    "Generate a monthly budget allocation as percentages summing to exactly 100. "
    "User context: {'monthly_income': 5000}. Answers: {'savings_goal': 'yes'}. "
    "Return ONLY a JSON object mapping category names to integer percentages. "
    'Example: {"housing": 30, "food": 20, "savings": 20, "transport": 10, '
    '"entertainment": 10, "utilities": 5, "other": 5}'
)


def test_budget_allocation_prompt_matches_hardcoded_output():
    """US3 acceptance #1 — template matches the old inline prompt incl. example JSON."""
    rendered = get_budget_allocation_prompt().render(
        user_context={"monthly_income": 5000}, answers={"savings_goal": "yes"}
    )
    assert rendered == _GOLDEN_BUDGET
    # The example JSON percentage breakdown must remain present and unescaped.
    assert '{"housing": 30, "food": 20' in rendered
    assert "&quot;" not in rendered
