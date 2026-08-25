"""Display tools — let the analysis agent attach a rich widget to its reply.

These sit alongside `get_transactions`/`compute_aggregate` in the analysis
agent's tool set. The split of responsibility matters: the **model** decides
*when* a widget would help, but the **tool** produces every figure in it by
querying the database itself. Nothing in a widget payload is ever authored by
the LLM, which is what keeps Principle VI's "never fabricating financial
figures" true for the rendered surface as well as the prose.

Built per-request via `make_widget_tools(user_id)`, mirroring
`make_transaction_tools` — `user_id` is closed over rather than exposed as a
tool argument, so a hallucinated or adversarial argument can never point a
lookup at another user's data.

The two data-shaped widgets delegate to the existing transaction tools rather
than re-implementing their SQL: `compute_aggregate(group_by="category")` is
already exactly a spending breakdown, and `get_transactions` is already exactly
a transaction list. Only the savings projection needs its own queries, because
no balance read path existed anywhere in the service before this.

Each tool returns a plain dict observation to the model *in addition to*
stashing the typed widget in the per-turn sink, so the model can narrate the
same figures in prose — the prose is what streams to the user as `token`
events. For the aggregate widgets (breakdown, projection) prose still states
the headline figures so a client that ignores widgets isn't left with
nothing. `show_transactions` is the one exception: its widget already IS the
full row-level answer, so its docstring asks for a short summary instead of a
duplicated table — see that tool's docstring for why.
"""

from __future__ import annotations

import decimal
import uuid
from typing import Literal

from langchain_core.tools import BaseTool, tool
from sqlalchemy import select

from app.backend_db.models import NetWorthSnapshot, Transaction
from app.core.logging import get_logger
from app.features.chat.schemas import (
    CategorySpend,
    SavingsSliderPayload,
    SavingsSliderWidget,
    SpendingBreakdownPayload,
    SpendingBreakdownWidget,
    TransactionListItem,
    TransactionsListPayload,
    TransactionsListWidget,
    Widget,
)
from app.tools.transactions import (
    _clean_optional,
    _parse_date,
    flow_for_type,
    make_transaction_tools,
)

logger = get_logger(__name__)

_MAX_LIST_ROWS = 50


def _dominant_currency(groups: list[dict]) -> str | None:
    """Picks the currency carrying the largest total.

    `compute_aggregate` deliberately never blends currencies — it returns one
    group per currency present — but a widget payload has a single `currency`
    field. Rather than sum unlike money, pick the currency the user actually
    transacts most in and render only that. Ties break alphabetically so the
    choice is deterministic across turns.
    """
    totals: dict[str, float] = {}
    for group in groups:
        currency = group.get("currency")
        value = group.get("value")
        if currency is None or value is None:
            continue
        totals[currency] = totals.get(currency, 0.0) + float(value)
    if not totals:
        return None
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _period_label(date_from: str | None, date_to: str | None) -> str:
    """Human display label for the breakdown's period.

    Only used when the model doesn't supply one — it usually phrases the period
    better than a date range can ("last month" beats "2026-07-01 – 2026-07-31").
    """
    if date_from is None and date_to is None:
        return "All time"
    try:
        start = _parse_date(date_from, "date_from")
        end = _parse_date(date_to, "date_to")
    except ValueError:
        return "Selected period"
    if start is not None and end is not None:
        if (start.year, start.month) == (end.year, end.month):
            return start.strftime("%B %Y")
        return f"{start.isoformat()} – {end.isoformat()}"
    anchor = start or end
    return anchor.strftime("%B %Y") if anchor else "Selected period"


async def _latest_net_worth(user_id: uuid.UUID) -> float | None:
    """Most recent `net_worth_snapshots.total_across_accounts`, if Django keeps
    that table populated. It is the schema's own current-balance concept —
    non-null and already summed across accounts — so it is preferred over the
    per-row running balance below.

    The table carries no currency column, so the caller pairs this with the
    currency derived from the user's transactions. That is an assumption, but a
    safe one: a snapshot totalling accounts the user does not transact in would
    be meaningless to them anyway.
    """
    stmt = (
        select(NetWorthSnapshot.total_across_accounts)
        .where(NetWorthSnapshot.user_id == user_id)
        .order_by(NetWorthSnapshot.as_of_date.desc())
        .limit(1)
    )
    from app.backend_db import get_backend_session

    async for session in get_backend_session():
        result = await session.execute(stmt)
        row = result.scalars().first()
        if row is not None:
            return float(row)
    return None


async def _latest_running_balance(user_id: uuid.UUID, currency: str) -> float | None:
    """Fallback balance: the newest non-null `transactions.balance` per account,
    summed over the given currency.

    `balance` is the running balance a statement stated for that row, so it is
    nullable (many statements state none) and only as fresh as the last ingested
    statement. Taking one row per account via DISTINCT ON avoids double-counting
    a user with several accounts.

    Selects two columns rather than the ORM entity — Principle III puts
    minimization at the query layer, and nothing here needs a whole transaction.
    """
    stmt = (
        select(Transaction.account_id, Transaction.balance)
        .where(
            Transaction.user_id == user_id,
            Transaction.currency == currency,
            Transaction.balance.is_not(None),
        )
        .order_by(
            Transaction.account_id,
            Transaction.transaction_date.desc(),
            Transaction.created_at.desc(),
        )
        .distinct(Transaction.account_id)
    )
    from app.backend_db import get_backend_session

    async for session in get_backend_session():
        result = await session.execute(stmt)
        balances = [row[1] for row in result.all() if row[1] is not None]
        if balances:
            return float(sum(decimal.Decimal(str(b)) for b in balances))
    return None


def make_widget_tools(
    user_id: uuid.UUID,
    transaction_tools: list[BaseTool] | None = None,
) -> tuple[list[BaseTool], list[Widget]]:
    """Builds the display tools for one authenticated user.

    Returns the tools plus the per-turn sink they append to. The sink is created
    fresh per call — it is request-scoped state, never shared between turns or
    users. The node reads the last entry after its tool loop finishes, so if the
    model calls two display tools the most recent one wins.

    `transaction_tools` is the caller's already-built list, so the node
    constructs them once and both families share the same closures rather than
    each building its own. It is looked up by name and treated as optional: a
    caller supplying a partial set gets display tools that report the gap at
    call time instead of failing to build the whole tool set.
    """
    sink: list[Widget] = []
    if transaction_tools is None:
        transaction_tools = make_transaction_tools(user_id)
    by_name = {t.name: t for t in transaction_tools}
    compute_aggregate = by_name.get("compute_aggregate")
    get_transactions = by_name.get("get_transactions")

    @tool
    async def show_spending_breakdown(
        date_from: str | None = None,
        date_to: str | None = None,
        month_label: str | None = None,
        currency: str | None = None,
    ) -> dict:
        """Display a per-category spending breakdown chart for a period.

        Call this in addition to answering when the user asks where their money
        went, for a spending or budget breakdown, or for spending by category.
        Still answer in prose as well — the chart supplements your reply, it
        does not replace it.

        Args:
            date_from: start of the period, ISO YYYY-MM-DD. Omit for no lower bound.
            date_to: end of the period, ISO YYYY-MM-DD. Omit for no upper bound.
            month_label: short display label for the period, e.g. "July 2026" or
                "Last month". Omit and one is derived from the dates.
            currency: 3-letter code to restrict to. Omit to use whichever
                currency the user spends most in.
        """
        if compute_aggregate is None:
            return {"error": "Spending aggregation is unavailable."}
        result = await compute_aggregate.ainvoke(
            {
                "op": "sum",
                "flow": "expense",
                "group_by": "category",
                "date_from": date_from,
                "date_to": date_to,
                "currency": currency,
            }
        )
        if not isinstance(result, dict) or "error" in result:
            return result if isinstance(result, dict) else {"error": "Aggregation failed."}

        groups = result.get("groups", [])
        chosen = _clean_optional(currency) or _dominant_currency(groups)
        if chosen is None:
            return {"shown": False, "reason": "No spending found for that period."}

        rows = [
            (str(g.get("category") or "uncategorized"), float(g["value"]))
            for g in groups
            if g.get("currency") == chosen and g.get("value") is not None and float(g["value"]) > 0
        ]
        total = sum(amount for _, amount in rows)
        if not rows or total <= 0:
            return {"shown": False, "reason": "No spending found for that period."}

        rows.sort(key=lambda row: -row[1])
        label = _clean_optional(month_label) or _period_label(date_from, date_to)
        payload = SpendingBreakdownPayload(
            currency=chosen,
            month=label,
            total=total,
            categories=[
                CategorySpend(name=name, amount=amount, pct=amount / total * 100)
                for name, amount in rows
            ],
        )
        sink.append(SpendingBreakdownWidget(payload=payload))
        return {
            "shown": True,
            "currency": chosen,
            "period": label,
            "total": total,
            "categories": [
                {"name": c.name, "amount": c.amount, "pct": round(c.pct, 1)}
                for c in payload.categories
            ],
        }

    @tool
    async def show_transactions(
        limit: int = 10,
        category: str | None = None,
        flow: Literal["income", "expense"] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Display a list of the user's transactions.

        Call this in addition to answering when the user asks to see their
        recent transactions, purchases, or history. Give a brief one- or
        two-sentence summary in prose (e.g. how many, the date range, the
        total) — do NOT enumerate the individual transactions as a list or
        markdown table; the widget already shows every row, so repeating them
        in prose is pure duplication.

        Args:
            category: category name to filter by. Omit for all categories.
            flow: "income" or "expense". Omit for both.
            date_from: earliest date, ISO YYYY-MM-DD. Omit for no lower bound.
            date_to: latest date, ISO YYYY-MM-DD. Omit for no upper bound.
            limit: how many rows to show. Capped at 50.
        """
        if get_transactions is None:
            return {"error": "Transaction lookup is unavailable."}
        capped = max(1, min(limit, _MAX_LIST_ROWS))
        result = await get_transactions.ainvoke(
            {
                "limit": capped,
                "category": category,
                "flow": flow,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        if not isinstance(result, dict) or "error" in result:
            return result if isinstance(result, dict) else {"error": "Lookup failed."}

        rows = result.get("transactions", [])
        if not rows:
            return {"shown": False, "reason": "No matching transactions."}

        # Single-currency payload, same reasoning as the breakdown: show the
        # currency most of the rows are in rather than listing unlike money
        # under one heading.
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["currency"]] = counts.get(row["currency"], 0) + 1
        chosen = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        items = [
            TransactionListItem(
                id=row["id"],
                title=row.get("merchant") or "Unknown",
                category=row.get("category") or "uncategorized",
                type=flow_for_type(row.get("transaction_type")),
                amount=float(row["amount"]),
                date=row["date"],
            )
            for row in rows
            if row.get("currency") == chosen
        ]
        if not items:
            return {"shown": False, "reason": "No matching transactions."}

        sink.append(
            TransactionsListWidget(
                payload=TransactionsListPayload(currency=chosen, transactions=items)
            )
        )
        return {"shown": True, "currency": chosen, "count": len(items)}

    @tool
    async def show_savings_projection() -> dict:
        """Display an interactive savings projection the user can explore.

        Call this in addition to answering when the user asks about saving
        money, how much they could save per month, or a savings projection.
        Still answer in prose as well.

        Needs both a known balance and enough income history; when either is
        missing this returns shown=false with a reason, and you should explain
        that plainly instead of estimating a figure yourself.
        """
        from app.features.plan.context import derive_planner_context

        context = await derive_planner_context(user_id)
        currency = context.get("currency")
        if not currency:
            return {
                "shown": False,
                "reason": (
                    "No transaction history yet, so there is no balance or income "
                    "to project from."
                ),
            }

        income = context.get("avg_monthly_income")
        recurring = context.get("avg_monthly_recurring_expense") or 0.0
        if income is None:
            return {
                "shown": False,
                "reason": "Not enough income history to suggest a monthly savings amount.",
            }

        try:
            balance = await _latest_net_worth(user_id)
            if balance is None:
                balance = await _latest_running_balance(user_id, currency)
        except Exception:
            logger.exception("show_savings_projection_balance_lookup_failed", user_id=str(user_id))
            return {"error": "Backend is unavailable."}

        if balance is None:
            return {
                "shown": False,
                "reason": (
                    "No account balance is available — the ingested statements don't state one."
                ),
            }

        default_savings = max(0.0, float(income) - float(recurring))
        sink.append(
            SavingsSliderWidget(
                payload=SavingsSliderPayload(
                    currency=currency,
                    current_balance=balance,
                    default_monthly_savings=default_savings,
                )
            )
        )
        return {
            "shown": True,
            "currency": currency,
            "current_balance": balance,
            "default_monthly_savings": default_savings,
        }

    tools: list[BaseTool] = [show_spending_breakdown, show_transactions, show_savings_projection]
    return tools, sink
