from __future__ import annotations

import datetime
import statistics
import uuid
from decimal import Decimal

from app.core.logging import get_logger
from app.features.investment_plan.schemas import InvestmentContext
from app.features.market_data.repository import list_curated_instruments

logger = get_logger(__name__)


def _three_complete_month_window(today: datetime.date) -> tuple[datetime.date, datetime.date]:
    first_this_month = today.replace(day=1)
    end = first_this_month - datetime.timedelta(days=1)
    year, month = end.year, end.month
    for _ in range(2):
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return datetime.date(year, month, 1), end


def _group_values(groups: list[dict], currency: str) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    for group in groups:
        if group.get("currency") != currency or not group.get("month"):
            continue
        values[str(group["month"])] = Decimal(str(group.get("value") or 0))
    return values


def _dominant_currency(groups: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    for group in groups:
        currency = group.get("currency")
        if currency and group.get("value") is not None:
            counts[currency] = counts.get(currency, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


async def _derive_surplus(user_id: uuid.UUID) -> dict:
    try:
        from app.features.plan.context import derive_planner_context
        from app.tools.transactions import make_transaction_tools

        tools = {item.name: item for item in make_transaction_tools(user_id)}
        aggregate = tools["compute_aggregate"]
        date_from, date_to = _three_complete_month_window(datetime.date.today())
        shared = {
            "op": "sum",
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "group_by": "month",
        }
        income_result = await aggregate.ainvoke({**shared, "flow": "income"})
        debit_result = await aggregate.ainvoke({**shared, "transaction_type": "debit"})
        fee_result = await aggregate.ainvoke({**shared, "transaction_type": "fee"})

        income_groups = income_result.get("groups", [])
        currency = _dominant_currency(income_groups)
        if currency is None:
            return {}
        income_by_month = _group_values(income_groups, currency)
        debit_by_month = _group_values(debit_result.get("groups", []), currency)
        fee_by_month = _group_values(fee_result.get("groups", []), currency)
        months = sorted(income_by_month)
        if not months:
            return {}

        income_values = [income_by_month[month] for month in months]
        expense_values = [
            debit_by_month.get(month, Decimal("0")) + fee_by_month.get(month, Decimal("0"))
            for month in months
        ]
        average_income = Decimal(str(statistics.mean(income_values)))
        average_expenses = Decimal(str(statistics.mean(expense_values)))

        planner_context = await derive_planner_context(user_id)
        target = planner_context.get("savings_goal_target_amount")
        timeline = planner_context.get("savings_goal_timeline_months")
        goal_commitment = (
            Decimal(str(target)) / Decimal(str(timeline))
            if target is not None and timeline is not None and timeline > 0
            else Decimal("0")
        )
        surplus = max(Decimal("0"), average_income - average_expenses - goal_commitment)
        return {
            "average_monthly_income": average_income.quantize(Decimal("0.01")),
            "average_monthly_expenses": average_expenses.quantize(Decimal("0.01")),
            "monthly_goal_commitment": goal_commitment.quantize(Decimal("0.01")),
            "estimated_monthly_surplus": surplus.quantize(Decimal("0.01")),
            "currency": currency,
            "months_used": len(months),
        }
    except Exception:
        logger.exception("derive_investment_surplus_failed", user_id=str(user_id))
        return {}


async def derive_investment_context(user_id: uuid.UUID) -> InvestmentContext:
    surplus = await _derive_surplus(user_id)
    try:
        instruments = await list_curated_instruments()
    except Exception:
        logger.exception("derive_investment_catalog_failed", user_id=str(user_id))
        instruments = []
    return InvestmentContext(**surplus, instruments=instruments)
