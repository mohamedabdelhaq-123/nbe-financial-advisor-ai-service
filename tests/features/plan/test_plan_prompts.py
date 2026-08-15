"""Golden-string test: plan prompt template preserves generate_plan()'s wording."""

from app.features.plan.prompts import get_budget_allocation_prompt

_GOLDEN_BUDGET = (
    "Generate a monthly budget allocation as percentages summing to exactly 100. "
    "User's average monthly income: 5000. "
    "Known recurring expenses: 1500. "
    "Known savings goal from their profile: a house deposit "
    "(target 100000, within 24 months). "
    "Questionnaire's savings_goal answer: yes. "
    "If these describe the same goal, don't double-count it; if they're "
    "different, treat both as goals to weigh when allocating savings. "
    "Questionnaire answers: {'savings_goal': 'yes', 'fixed_expenses': 'rent 1500'}. "
    "Return ONLY a JSON object mapping category names to integer percentages, "
    "using ONLY these category names: housing, food, savings. "
    "Example: {'housing': 10, 'food': 10, 'savings': 10}"
)


def test_budget_allocation_prompt_matches_generate_plan_output():
    """Template output matches generate_plan()'s inline-prompt wording exactly."""
    known_categories = ["housing", "food", "savings"]
    rendered = get_budget_allocation_prompt().render(
        avg_monthly_income=5000,
        avg_monthly_recurring_expense=1500,
        savings_goal_name="a house deposit",
        savings_goal_target_amount=100000,
        savings_goal_timeline_months=24,
        savings_goal_answer="yes",
        answers={"savings_goal": "yes", "fixed_expenses": "rent 1500"},
        known_categories=known_categories,
        example_categories=", ".join(f"{c!r}: 10" for c in known_categories),
    )
    assert rendered == _GOLDEN_BUDGET
    # The live-category constraint must remain present verbatim in the rendered text.
    assert "using ONLY these category names: housing, food, savings" in rendered
