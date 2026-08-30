"""Read-only ledger lookup and aggregation tools for the analysis agent.

All tools are built per-request via `make_transaction_tools(user_id)`, which
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

`find_similar_transactions` is the semantic tool for the case the structured
transaction tools can't handle: a vague description with no clean filter ("that coffee
place last week", "my streaming subscriptions"). It ranks by cosine
similarity against `Transaction.embedding` — populated from
`f"{merchant}, {category}, {amount} {currency}, {date}"` by
`app.features.transactions.service.embed_transactions` — rather than
filtering on structured columns. Rows with no embedding yet are excluded, not
treated as non-matches, since the two are different states.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import selectinload

from app.backend_db.models import (
    TRANSACTION_EMBEDDING_DIM,
    BankAccount,
    Category,
    Transaction,
)
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


def flow_for_type(transaction_type: str | None) -> Literal["income", "expense"]:
    """Inverse of `_flow_types` — maps one raw row's type to the income/expense
    grouping the frontend shows. Public because the widget tools project rows
    into a payload with an `income`/`expense` field and must use this exact
    mapping, not a second guess at it: everything that isn't a credit (debit,
    fee, AND transfer) is an expense. A NULL type is stored as a debit by
    convention, matching `get_transactions`'s own fallback below.
    """
    return "income" if (transaction_type or "debit") == "credit" else "expense"


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


class SimilarTransactionRow(TransactionRow):
    similarity: float


async def calculate_current_balances(
    user_id: uuid.UUID,
    currency: str | None = None,
) -> list[dict]:
    """Derive live balances for the user's active accounts, grouped by currency.

    The newest non-null running balance on each account is the bank-stated
    anchor. Every later amount-only transaction is applied by direction
    (credit adds; debit/fee/transfer/NULL subtract). If an account has never
    carried a stated balance, its complete ledger is applied from zero. This
    deliberately matches Django's ``BankAccount.current_balance`` rule.
    """
    account_stmt = select(BankAccount).where(
        BankAccount.user_id == user_id,
        BankAccount.is_active.is_(True),
    )
    if currency is not None:
        account_stmt = account_stmt.where(BankAccount.currency == currency.upper())
    account_stmt = account_stmt.order_by(BankAccount.created_at, BankAccount.id)

    grouped: dict[str, dict] = {}

    from app.backend_db import get_backend_session

    async for session in get_backend_session():
        account_result = await session.execute(account_stmt)
        accounts = account_result.scalars().all()

        for account in accounts:
            anchor_stmt = (
                select(
                    Transaction.balance,
                    Transaction.transaction_date,
                    Transaction.created_at,
                )
                .where(
                    Transaction.account_id == account.id,
                    Transaction.balance.is_not(None),
                )
                .order_by(
                    Transaction.transaction_date.desc(),
                    Transaction.created_at.desc(),
                )
                .limit(1)
            )
            anchor = (await session.execute(anchor_stmt)).first()

            movement_filters = [Transaction.account_id == account.id]
            base = decimal.Decimal("0")
            anchor_date = None
            if anchor is not None:
                anchor_balance, anchor_date, anchor_created_at = anchor
                base = decimal.Decimal(str(anchor_balance))
                movement_filters.append(
                    or_(
                        Transaction.transaction_date > anchor_date,
                        and_(
                            Transaction.transaction_date == anchor_date,
                            Transaction.created_at > anchor_created_at,
                        ),
                    )
                )

            signed_amount = case(
                (Transaction.transaction_type == "credit", Transaction.amount),
                else_=-Transaction.amount,
            )
            movement_stmt = select(
                func.coalesce(func.sum(signed_amount), 0),
                func.max(Transaction.transaction_date),
            ).where(*movement_filters)
            delta, latest_movement_date = (await session.execute(movement_stmt)).one()
            current = base + decimal.Decimal(str(delta))
            as_of_date = latest_movement_date or anchor_date

            group = grouped.setdefault(
                account.currency,
                {
                    "currency": account.currency,
                    "current_balance": decimal.Decimal("0"),
                    "accounts": [],
                },
            )
            group["current_balance"] += current
            group["accounts"].append(
                {
                    "account_id": str(account.id),
                    "bank_name": account.bank_name,
                    "account_number_last4": account.account_number[-4:],
                    "current_balance": float(current),
                    "as_of_date": as_of_date.isoformat() if as_of_date else None,
                }
            )

    return [
        {
            **group,
            "current_balance": float(group["current_balance"]),
        }
        for _, group in sorted(grouped.items())
    ]


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
    async def get_current_balance(currency: str | None = None) -> dict:
        """Return the user's live current balance across active bank accounts.

        Always use this tool for questions such as "what is my balance?",
        "how much money do I have right now?", or "what is in my account?".
        Never derive a current balance by subtracting lifetime expenses from
        lifetime income: transaction history can start with a non-zero bank
        balance. Results are grouped by currency and include an account-level
        breakdown.

        Args:
            currency: optional 3-letter currency code such as ``EGP``. Omit
                to return one balance group for every currency held.
        """
        currency = _clean_optional(currency)
        try:
            groups = await calculate_current_balances(user_id, currency)
        except Exception:
            logger.exception("get_current_balance_tool_failed", user_id=str(user_id))
            return {"error": "Backend is unavailable."}

        if not groups:
            return {
                "groups": [],
                "note": "No active bank accounts were found for this user.",
            }
        return {
            "groups": groups,
            "method": (
                "Newest bank-stated running balance per account, plus every "
                "newer credit and minus every newer outflow."
            ),
        }

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

        payload: dict = {"groups": groups}
        if flow is None and transaction_type is None:
            # The docstring already tells the model to prefer flow for
            # spending/income questions, but that's a pre-call instruction
            # competing with everything else in context — confirmed live
            # that a model can still omit both and blend income in with
            # spending, reporting a category total many times too large.
            # This note rides along with the actual number being reported,
            # right when the model is about to state it, which is a much
            # harder signal to miss than the docstring alone.
            payload["note"] = (
                "This total blends every transaction type together — income, "
                "expenses, fees, and transfers — because neither flow nor "
                "transaction_type was given. For a spending-only or income-only "
                'figure, call again with flow="expense" or flow="income".'
            )
        return payload

    @tool
    async def find_similar_transactions(query: str, top_k: int = 5) -> dict:
        """Find the user's transactions that best match a vague, free-text
        description — not a structured filter.

        Use this only when the request has no clean category/merchant/date
        filter for get_transactions, e.g. "that coffee place last week" or
        "my streaming subscriptions". For anything with a clear filter (a
        category name, an exact date range, income vs expense), prefer
        get_transactions instead — it is exact; this is a best-effort ranking.

        Args:
            query: the vague description to match against, in the user's own words.
            top_k: max rows to return, ranked by similarity. Capped at 20.
        """
        query = query.strip()
        if not query:
            return {"error": "query must not be empty."}
        capped_top_k = max(1, min(top_k, 20))

        try:
            from app.features.embed.service import embed_texts

            vectors = await embed_texts([query], dimensions=TRANSACTION_EMBEDDING_DIM)
        except Exception:
            logger.exception("find_similar_transactions_embed_failed", user_id=str(user_id))
            return {"error": "Could not process that description."}

        query_vec = vectors[0] if vectors else []
        if not query_vec:
            return {"error": "Could not process that description."}

        similarity = 1 - Transaction.embedding.cosine_distance(query_vec)
        stmt = (
            select(Transaction, similarity.label("score"))
            .where(Transaction.user_id == user_id)
            .where(Transaction.embedding.isnot(None))
            .options(selectinload(Transaction.category))
            .order_by(similarity.desc())
            .limit(capped_top_k)
        )

        try:
            from app.backend_db import get_backend_session

            async for session in get_backend_session():
                result = await session.execute(stmt)
                rows = result.all()
        except Exception:
            logger.exception("find_similar_transactions_tool_failed", user_id=str(user_id))
            return {"error": "Backend is unavailable."}

        return {
            "count": len(rows),
            "transactions": [
                SimilarTransactionRow(
                    id=str(txn.id),
                    date=txn.transaction_date,
                    amount=float(txn.amount),
                    currency=txn.currency,
                    transaction_type=txn.transaction_type or "debit",
                    merchant=txn.merchant_raw or "unknown",
                    category=txn.category.name if txn.category else "uncategorized",
                    similarity=float(score),
                ).model_dump(mode="json")
                for txn, score in rows
            ],
        }

    return [
        get_current_balance,
        get_transactions,
        compute_aggregate,
        find_similar_transactions,
    ]
