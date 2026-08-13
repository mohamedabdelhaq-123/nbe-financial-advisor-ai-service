"""Derives real per-user financial signal for the budget planner.

Per Pipeline.md §3/§5, Maestro is meant to assemble user context before
delegating to a sub-agent — this is what it calls to do that for planning.
`user_context`/`ChatTurnRequest.initial_context` is dead plumbing in
production (Django never populates it), so the only real source of
per-user signal is the transaction data already sitting in the backend DB,
plus signup/onboarding data the user already gave once (dependents count,
savings goal) that otherwise just sits unused. Reuses
`app.tools.transactions.make_transaction_tools` directly rather than
re-implementing queries — same read-only, `ai_readonly`-role-bound access
`analysis_node` already uses.
"""

import statistics
import uuid
from typing import TypedDict

from app.core.logging import get_logger

logger = get_logger(__name__)


class PlannerContext(TypedDict, total=False):
    avg_monthly_income: float | None
    income_variance_ratio: float | None
    months_of_income_data: int
    avg_monthly_recurring_expense: float | None
    currency: str | None
    # From signup/onboarding — see _derive_profile_signal's docstring for
    # why dependents_count needs the onboarding_date gate.
    dependents_count: int | None
    savings_goal_name: str | None
    savings_goal_target_amount: float | None
    savings_goal_timeline_months: int | None


def _dominant_currency_values(groups: list[dict]) -> tuple[str | None, list[float]]:
    """Picks the currency with the most monthly groups present — per-group
    results are always broken out by currency (never blended, matching
    app.tools.transactions's own design), so a user with multiple
    currencies needs one picked rather than mixed together. Ties broken
    alphabetically for determinism."""
    by_currency: dict[str, list[float]] = {}
    for g in groups:
        currency = g.get("currency")
        value = g.get("value")
        if currency is None or value is None:
            continue
        by_currency.setdefault(currency, []).append(float(value))

    if not by_currency:
        return None, []

    best_currency = sorted(by_currency.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]
    return best_currency, by_currency[best_currency]


async def _derive_income_signal(user_id: uuid.UUID) -> dict:
    """Never raises — a derivation failure must degrade to the generic
    questionnaire, never fail the chat turn. Zero transactions (a new
    user) produces the same neutral result as a backend failure. Kept
    independent from _derive_profile_signal: a failure here must not blank
    out a profile/goal lookup that already succeeded, or vice versa."""
    try:
        from app.tools.transactions import make_transaction_tools

        tools = {t.name: t for t in make_transaction_tools(user_id)}
        compute_aggregate = tools["compute_aggregate"]

        income_result = await compute_aggregate.ainvoke(
            {"op": "sum", "flow": "income", "group_by": "month"}
        )
        recurring_result = await compute_aggregate.ainvoke(
            {"op": "sum", "flow": "expense", "is_recurring": True, "group_by": "month"}
        )

        income_groups = income_result.get("groups", []) if isinstance(income_result, dict) else []
        recurring_groups = (
            recurring_result.get("groups", []) if isinstance(recurring_result, dict) else []
        )

        currency, income_values = _dominant_currency_values(income_groups)
        months_of_income_data = len(income_values)

        avg_monthly_income = statistics.mean(income_values) if income_values else None
        income_variance_ratio = None
        if months_of_income_data >= 2 and avg_monthly_income:
            income_variance_ratio = statistics.pstdev(income_values) / avg_monthly_income

        recurring_currency, recurring_values = _dominant_currency_values(recurring_groups)
        avg_monthly_recurring_expense = (
            statistics.mean(recurring_values) if recurring_values else None
        )

        return {
            "avg_monthly_income": avg_monthly_income,
            "income_variance_ratio": income_variance_ratio,
            "months_of_income_data": months_of_income_data,
            "avg_monthly_recurring_expense": avg_monthly_recurring_expense,
            "currency": currency or recurring_currency,
        }
    except Exception:
        logger.exception("derive_planner_context_income_signal_failed", user_id=str(user_id))
        return {
            "avg_monthly_income": None,
            "income_variance_ratio": None,
            "months_of_income_data": 0,
            "avg_monthly_recurring_expense": None,
            "currency": None,
        }


async def _derive_profile_signal(user_id: uuid.UUID) -> dict:
    """Never raises, same discipline as _derive_income_signal.

    `dependents_count` is a not-null column defaulting to 0 — a bare read
    can't distinguish "genuinely no dependents" from "onboarding step never
    completed." `onboarding_date` (nullable, set only once onboarding
    finishes) is the clean gate: only trust dependents_count once it's set.
    A missing `Goal` row (user never set one) is a normal `None`, not an
    error — `scalar_one_or_none()` handles that without raising.
    """
    result: dict[str, int | str | float | None] = {
        "dependents_count": None,
        "savings_goal_name": None,
        "savings_goal_target_amount": None,
        "savings_goal_timeline_months": None,
    }
    try:
        from sqlalchemy import select

        from app.backend_db import get_backend_session
        from app.backend_db.models import Goal, User

        async for session in get_backend_session():
            user_row = await session.get(User, user_id)
            if user_row is not None and user_row.onboarding_date is not None:
                result["dependents_count"] = user_row.dependents_count

            goal_row = (
                await session.execute(select(Goal).where(Goal.user_id == user_id))
            ).scalar_one_or_none()
            if goal_row is not None:
                result["savings_goal_name"] = goal_row.name
                result["savings_goal_target_amount"] = float(goal_row.target_amount)
                result["savings_goal_timeline_months"] = goal_row.timeline_months
    except Exception:
        logger.exception("derive_planner_context_profile_signal_failed", user_id=str(user_id))
    return result


async def derive_planner_context(user_id: uuid.UUID) -> PlannerContext:
    income_signal = await _derive_income_signal(user_id)
    profile_signal = await _derive_profile_signal(user_id)
    return {**income_signal, **profile_signal}  # type: ignore[typeddict-item]
