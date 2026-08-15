"""Read-only transaction lookup and aggregation tools for the analysis agent.

Both tools are built per-request via `make_transaction_tools(user_id)`, which
closes over the authenticated user_id from `ConversationState` rather than
exposing it as a tool argument — the LLM chooses filters (category, date
range, ...), never whose data it reads, so a hallucinated or adversarial
argument can never point a lookup at another user's transactions. Queries
run through `get_backend_session()`, which is bound to the `ai_readonly`
Postgres role (see app/backend_db/__init__.py) — the database itself
rejects any write, independent of this module.

`amount` is stored as an unsigned magnitude; `transaction_type` is what
distinguishes spend from income, with FOUR real values in this DB —
"debit", "credit", "fee", "transfer" (see
app/features/ingestion/normalizer/schemas.py) — not just debit/credit.
Summing `amount` with no type filter blends all four into a meaningless
number, so `compute_aggregate` takes `transaction_type`/`flow` as explicit
filters rather than always summing everything.

"income"/"expense" as shown in the frontend is not the raw column — it's a
derived grouping the Django backend defines explicitly (see
TransactionFilterSet.filter_type in the backend's
core/filters/aggregations.py): income = credit; expense = debit + fee +
transfer. The `flow` argument below mirrors that exact mapping so the tool
answers "how much did I spend" the same way the rest of the product does.
`transaction_type` remains available for precise single-type filters (e.g.
"how much did I pay in fees").
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.backend_db.models import Category, Transaction
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_LIMIT = 50
# Mirrors TransactionFilterSet.filter_type in the Django backend exactly —
# expense is NOT just "debit"; fee and transfer rows are expense too.
_EXPENSE_TYPES = ("debit", "fee", "transfer")


def _flow_types(flow: Literal["income", "expense"] | None) -> tuple[str, ...] | None:
    if flow is None:
        return None
    return ("credit",) if flow == "income" else _EXPENSE_TYPES


_NONE_SENTINELS = {"none", "null", ""}


def _clean_optional(value: str | None) -> str | None:
    """Treats a model sending the literal string "none"/"null"/"" for an
    unset optional field the same as actually omitting it. Confirmed against
    the configured OpenRouter model (Nemotron): it fills every optional
    plain-`str` argument rather than leaving it out, and unlike a `Literal`
    field, an invalid string here doesn't raise — it silently becomes a
    filter that matches nothing (e.g. `currency = 'NONE'`), which is worse
    than an error since it looks like a legitimate empty result instead of
    a bad argument."""
    if value is None or value.strip().lower() in _NONE_SENTINELS:
        return None
    return value


class TransactionRow(BaseModel):
    id: str
    date: datetime.date
    amount: float
    currency: str
    transaction_type: str
    merchant: str
    category: str


def _parse_date(raw: str | None, field: str) -> datetime.date | None:
    if raw is None:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD), got {raw!r}") from exc


def _to_number(value: decimal.Decimal | int | None, op: str) -> float | int | None:
    if value is None:
        return None
    return int(value) if op == "count" else float(value)


def make_transaction_tools(user_id: uuid.UUID) -> list[BaseTool]:
    """Builds the transaction tools scoped to one authenticated user.

    Called once per turn in the analysis node, with the user_id already
    resolved from ConversationState — see the closure note in the module
    docstring for why user_id is never a tool argument.
    """

    @tool
    async def get_transactions(
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        currency: str | None = None,
        flow: Literal["income", "expense"] | None = None,
        transaction_type: Literal["debit", "credit", "fee", "transfer"] | None = None,
        is_recurring: bool | None = None,
        limit: int = 10,
    ) -> dict:
        """Look up the user's own transactions, optionally filtered. Returns newest first.

        Use this to show or list specific transactions. To total, average, or
        otherwise calculate over transactions, call compute_aggregate instead —
        do not sum or average the rows this returns yourself.

        Args:
            category: category name to filter by (e.g. "groceries"), case-insensitive
                partial match against the category name. Omit for all categories.
            date_from: earliest transaction date, ISO format YYYY-MM-DD. Omit for no
                lower bound.
            date_to: latest transaction date, ISO format YYYY-MM-DD. Omit for no
                upper bound.
            currency: 3-letter currency code to filter by (e.g. "EGP"). Omit for all
                currencies — results may then mix currencies, each row states its own.
            flow: "income" or "expense", matching what the user sees in the app.
                Prefer this over transaction_type for plain requests like "show my
                spending" — "expense" already covers debit, fee, AND transfer rows.
            transaction_type: exact underlying type — "debit", "credit", "fee", or
                "transfer" — for precise single-type requests (e.g. "just my fees").
                Combine with flow only if you deliberately want both filters applied.
            is_recurring: filter to only recurring (True) or only one-off (False)
                transactions. Omit for both.
            limit: max rows to return. Capped at 50 regardless of what's requested.
        """
        try:
            parsed_from = _parse_date(date_from, "date_from")
            parsed_to = _parse_date(date_to, "date_to")
        except ValueError as exc:
            return {"error": str(exc)}

        category = _clean_optional(category)
        currency = _clean_optional(currency)
        capped_limit = max(1, min(limit, _MAX_LIMIT))

        stmt = (
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .options(selectinload(Transaction.category))
            .order_by(Transaction.transaction_date.desc())
            .limit(capped_limit)
        )
        if parsed_from is not None:
            stmt = stmt.where(Transaction.transaction_date >= parsed_from)
        if parsed_to is not None:
            stmt = stmt.where(Transaction.transaction_date <= parsed_to)
        if currency is not None:
            stmt = stmt.where(Transaction.currency == currency.upper())
        flow_types = _flow_types(flow)
        if flow_types is not None:
            stmt = stmt.where(Transaction.transaction_type.in_(flow_types))
        if transaction_type is not None:
            stmt = stmt.where(Transaction.transaction_type == transaction_type)
        if is_recurring is not None:
            stmt = stmt.where(Transaction.is_recurring == is_recurring)
        if category is not None:
            stmt = stmt.join(Transaction.category).where(Category.name.ilike(f"%{category}%"))

        try:
            from app.backend_db import get_backend_session

            async for session in get_backend_session():
                result = await session.execute(stmt)
                rows = result.scalars().all()
        except Exception:
            logger.exception("get_transactions_tool_failed", user_id=str(user_id))
            return {"error": "Backend is unavailable."}

        return {
            "count": len(rows),
            "transactions": [
                TransactionRow(
                    id=str(txn.id),
                    date=txn.transaction_date,
                    amount=float(txn.amount),
                    currency=txn.currency,
                    transaction_type=txn.transaction_type or "debit",
                    merchant=txn.merchant_raw or "unknown",
                    category=txn.category.name if txn.category else "uncategorized",
                ).model_dump(mode="json")
                for txn in rows
            ],
        }

    @tool
    async def compute_aggregate(
        op: Literal["sum", "avg", "count", "min", "max"],
        flow: Literal["income", "expense"] | None = None,
        transaction_type: Literal["debit", "credit", "fee", "transfer"] | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        currency: str | None = None,
        is_recurring: bool | None = None,
        group_by: Literal["category", "month"] | None = None,
    ) -> dict:
        """Computes sum/average/count/min/max over the user's transactions, server-side.

        Always use this for totals, averages, or counts — never estimate or add up
        figures yourself from get_transactions rows, and never report a number this
        tool didn't return.

        Results are always broken out by currency (see "currency" in each returned
        group) rather than blended into one figure — pass `currency` yourself only
        if you already know the user has just one.

        Args:
            op: the aggregate to compute.
            flow: "income" or "expense", matching what the user sees in the app —
                "expense" covers debit, fee, AND transfer rows, not just debit. Use
                this (not transaction_type) for plain "how much did I spend/earn"
                questions. Strongly recommended: omitting both flow and
                transaction_type sums spend, income, fees, and transfers together,
                which is almost never what's being asked.
            transaction_type: exact underlying type, for precise single-type totals
                (e.g. "how much did I pay in fees"). Combine with flow only if you
                deliberately want both filters applied.
            category: restrict to one category (e.g. "groceries") before aggregating.
                Omit for all categories.
            date_from: earliest transaction date, ISO YYYY-MM-DD. Omit for no lower bound.
            date_to: latest transaction date, ISO YYYY-MM-DD. Omit for no upper bound.
            currency: restrict to one currency code (e.g. "EGP"). Omit to get one group
                per currency present instead.
            is_recurring: filter to only recurring (True) or only one-off (False)
                transactions. Omit for both.
            group_by: break the total down by category or by calendar month, instead
                of one figure per currency.
        """
        try:
            parsed_from = _parse_date(date_from, "date_from")
            parsed_to = _parse_date(date_to, "date_to")
        except ValueError as exc:
            return {"error": str(exc)}

        category = _clean_optional(category)
        currency = _clean_optional(currency)

        agg_fn = {
            "sum": func.sum(Transaction.amount),
            "avg": func.avg(Transaction.amount),
            "count": func.count(Transaction.id),
            "min": func.min(Transaction.amount),
            "max": func.max(Transaction.amount),
        }[op]

        group_cols: list[Any] = [Transaction.currency]
        if group_by == "category":
            group_cols.append(Category.name)
        elif group_by == "month":
            group_cols.append(func.date_trunc("month", Transaction.transaction_date))

        stmt = select(*group_cols, agg_fn.label("value")).where(Transaction.user_id == user_id)
        if parsed_from is not None:
            stmt = stmt.where(Transaction.transaction_date >= parsed_from)
        if parsed_to is not None:
            stmt = stmt.where(Transaction.transaction_date <= parsed_to)
        if currency is not None:
            stmt = stmt.where(Transaction.currency == currency.upper())
        flow_types = _flow_types(flow)
        if flow_types is not None:
            stmt = stmt.where(Transaction.transaction_type.in_(flow_types))
        if transaction_type is not None:
            stmt = stmt.where(Transaction.transaction_type == transaction_type)
        if is_recurring is not None:
            stmt = stmt.where(Transaction.is_recurring == is_recurring)

        # Explicit category filter narrows to matching rows only (inner join is
        # correct there). Grouping by category with no filter must keep
        # uncategorized transactions visible instead of silently dropping them,
        # so that path uses an outer join.
        if category is not None:
            stmt = stmt.join(Transaction.category).where(Category.name.ilike(f"%{category}%"))
        elif group_by == "category":
            stmt = stmt.outerjoin(Transaction.category)

        stmt = stmt.group_by(*group_cols)

        try:
            from app.backend_db import get_backend_session

            async for session in get_backend_session():
                result = await session.execute(stmt)
                rows = result.all()
        except Exception:
            logger.exception("compute_aggregate_tool_failed", user_id=str(user_id))
            return {"error": "Backend is unavailable."}

        groups = []
        for row in rows:
            *dims, value = row
            entry: dict = {"currency": dims[0], "value": _to_number(value, op)}
            if group_by == "category":
                entry["category"] = dims[1] or "uncategorized"
            elif group_by == "month":
                entry["month"] = dims[1].strftime("%Y-%m") if dims[1] else None
            groups.append(entry)

        return {"groups": groups}

    return [get_transactions, compute_aggregate]
