"""Budget planning service — question generation and plan creation."""

from decimal import Decimal

from app.core.config import settings
from app.features.plan.schemas import BudgetAllocation, PlanQuestion

MAX_QUESTIONS = 7

QUESTIONS = [
    PlanQuestion(id="income_stability", text="Is your monthly income consistent or variable?"),
    PlanQuestion(
        id="fixed_expenses",
        text="What are your fixed monthly obligations (rent, loans, subscriptions)?",
    ),
    PlanQuestion(id="savings_goal", text="Do you have a specific savings goal or target amount?"),
    PlanQuestion(id="dependents", text="How many dependents do you financially support?"),
    PlanQuestion(
        id="risk_tolerance", text="How comfortable are you with financial risk (low/medium/high)?"
    ),
    PlanQuestion(id="debt", text="Do you have any outstanding debts beyond fixed obligations?"),
    PlanQuestion(
        id="lifestyle",
        text="How would you describe your spending lifestyle (frugal/moderate/generous)?",
    ),
]


async def next_question(
    user_context: dict,
    answers: dict,
    questions_asked: int,
) -> PlanQuestion | None:
    if questions_asked >= MAX_QUESTIONS:
        return None

    answered = set(answers.keys())
    for q in QUESTIONS:
        if q.id not in answered:
            return q
    return None


async def generate_plan(
    user_context: dict,
    answers: dict,
) -> list[BudgetAllocation]:
    if settings.use_mock_llm:
        return _mock_plan(answers)

    from app.core.llm import get_chat_model

    llm = get_chat_model()
    prompt = (
        f"Generate a monthly budget allocation as percentages summing to exactly 100. "
        f"User context: {user_context}. Answers: {answers}. "
        f"Return ONLY a JSON object mapping category names to integer percentages. "
        f'Example: {{"housing": 30, "food": 20, "savings": 20, "transport": 10, '
        f'"entertainment": 10, "utilities": 5, "other": 5}}'
    )
    response = await llm.ainvoke(prompt)
    raw = str(response.content).strip()

    allocations = _parse_and_normalize(raw)
    return allocations


def _mock_plan(answers: dict) -> list[BudgetAllocation]:
    savings_pct = 20
    if answers.get("savings_goal", "").lower() in ("yes", "aggressive"):
        savings_pct = 30
    elif answers.get("dependents", ""):
        savings_pct = 15

    housing = 30
    if answers.get("fixed_expenses", ""):
        housing = 35

    remaining = 100 - savings_pct - housing

    allocations = [
        BudgetAllocation(category="housing", percentage=Decimal(str(housing))),
        BudgetAllocation(category="food", percentage=Decimal("15")),
        BudgetAllocation(category="transport", percentage=Decimal("10")),
        BudgetAllocation(category="savings", percentage=Decimal(str(savings_pct))),
        BudgetAllocation(category="utilities", percentage=Decimal("5")),
    ]

    leftover = remaining - 15 - 10 - 5
    if leftover > 0:
        allocations.append(
            BudgetAllocation(category="entertainment", percentage=Decimal(str(leftover)))
        )

    total = sum(a.percentage for a in allocations)
    if total != 100:
        diff = Decimal("100") - total
        allocations[0] = BudgetAllocation(
            category=allocations[0].category,
            percentage=allocations[0].percentage + diff,
        )

    total = sum(a.percentage for a in allocations)
    assert total == 100, f"Mock plan must sum to 100, got {total}"
    return allocations


def _parse_and_normalize(raw: str) -> list[BudgetAllocation]:
    import json
    import re

    json_match = re.search(r"\{[^}]+\}", raw)
    if not json_match:
        return _mock_plan({})

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return _mock_plan({})

    allocations = []
    for category, pct in data.items():
        allocations.append(BudgetAllocation(category=category, percentage=Decimal(str(int(pct)))))

    total = sum(a.percentage for a in allocations)
    if total != 100:
        diff = Decimal("100") - total
        if allocations:
            allocations[0] = BudgetAllocation(
                category=allocations[0].category,
                percentage=allocations[0].percentage + diff,
            )

    final_total = sum(a.percentage for a in allocations)
    assert final_total == 100, f"Plan must sum to 100, got {final_total}"
    return allocations
