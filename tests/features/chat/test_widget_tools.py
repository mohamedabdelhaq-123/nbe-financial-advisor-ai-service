"""Unit tests for app.tools.widgets — the analysis agent's display tools.

The invariant under test throughout: every figure in a widget payload comes
from a query, never from the model. Each test therefore drives the tools with
stubbed *data* (a fake aggregate result, fake rows, a fake planner context) and
asserts on the typed widget that lands in the sink.
"""

import datetime
import uuid

import pytest
from langchain_core.tools import tool

from app.features.chat.schemas import (
    SavingsSliderWidget,
    SpendingBreakdownWidget,
    TransactionsListWidget,
)
from app.tools.widgets import make_widget_tools

_USER_ID = uuid.UUID("70b8d118-9b58-45ab-a8ad-4af9ce9105df")


def _fake_transaction_tools(*, aggregate=None, transactions=None):
    """Stand-ins for the two real transaction tools, matching their names and
    return shapes exactly so the display tools exercise their real delegation
    path (Principle I: mock responses match the production shape)."""

    @tool
    async def compute_aggregate(
        op: str,
        flow: str | None = None,
        transaction_type: str | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        currency: str | None = None,
        is_recurring: bool | None = None,
        group_by: str | None = None,
    ) -> dict:
        """Fake aggregate."""
        return aggregate if aggregate is not None else {"groups": []}

    @tool
    async def get_transactions(
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        currency: str | None = None,
        flow: str | None = None,
        transaction_type: str | None = None,
        is_recurring: bool | None = None,
        limit: int = 10,
    ) -> dict:
        """Fake lookup."""
        rows = transactions if transactions is not None else []
        return {"count": len(rows), "transactions": rows}

    return [compute_aggregate, get_transactions]


def _tools(*, aggregate=None, transactions=None):
    return make_widget_tools(
        _USER_ID, _fake_transaction_tools(aggregate=aggregate, transactions=transactions)
    )


def _by_name(tools, name):
    return next(t for t in tools if t.name == name)


# --------------------------------------------------------------------------
# show_spending_breakdown
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spending_breakdown_percentages_sum_to_100_and_total_matches():
    tools, sink = _tools(
        aggregate={
            "groups": [
                {"currency": "EGP", "category": "groceries", "value": 250.0},
                {"currency": "EGP", "category": "housing", "value": 750.0},
            ]
        }
    )

    result = await _by_name(tools, "show_spending_breakdown").ainvoke(
        {"date_from": "2026-07-01", "date_to": "2026-07-31"}
    )

    assert result["shown"] is True
    assert len(sink) == 1
    widget = sink[-1]
    assert isinstance(widget, SpendingBreakdownWidget)
    assert widget.type == "spending_breakdown"

    payload = widget.payload
    assert payload.currency == "EGP"
    assert payload.total == pytest.approx(1000.0)
    assert sum(c.amount for c in payload.categories) == pytest.approx(payload.total)
    assert sum(c.pct for c in payload.categories) == pytest.approx(100.0)
    # Highest spend first, so the chart legend reads in a sensible order.
    assert [c.name for c in payload.categories] == ["housing", "groceries"]
    assert payload.categories[0].pct == pytest.approx(75.0)


@pytest.mark.asyncio
async def test_spending_breakdown_derives_month_label_from_dates():
    tools, sink = _tools(
        aggregate={"groups": [{"currency": "EGP", "category": "groceries", "value": 10.0}]}
    )

    await _by_name(tools, "show_spending_breakdown").ainvoke(
        {"date_from": "2026-07-01", "date_to": "2026-07-31"}
    )

    assert sink[-1].payload.month == "July 2026"


@pytest.mark.asyncio
async def test_spending_breakdown_prefers_model_supplied_label():
    tools, sink = _tools(
        aggregate={"groups": [{"currency": "EGP", "category": "groceries", "value": 10.0}]}
    )

    await _by_name(tools, "show_spending_breakdown").ainvoke(
        {"date_from": "2026-07-01", "date_to": "2026-07-31", "month_label": "Last month"}
    )

    assert sink[-1].payload.month == "Last month"


@pytest.mark.asyncio
async def test_spending_breakdown_never_blends_currencies():
    """compute_aggregate returns one group per currency; the payload has a
    single `currency`, so the tool must pick one rather than sum unlike money."""
    tools, sink = _tools(
        aggregate={
            "groups": [
                {"currency": "EGP", "category": "groceries", "value": 900.0},
                {"currency": "USD", "category": "travel", "value": 100.0},
            ]
        }
    )

    await _by_name(tools, "show_spending_breakdown").ainvoke({})

    payload = sink[-1].payload
    assert payload.currency == "EGP"
    assert payload.total == pytest.approx(900.0)
    assert [c.name for c in payload.categories] == ["groceries"]


@pytest.mark.asyncio
async def test_spending_breakdown_emits_no_widget_when_no_spending():
    tools, sink = _tools(aggregate={"groups": []})

    result = await _by_name(tools, "show_spending_breakdown").ainvoke({})

    assert result["shown"] is False
    assert sink == []


@pytest.mark.asyncio
async def test_spending_breakdown_propagates_backend_error_and_emits_no_widget():
    tools, sink = _tools(aggregate={"error": "Backend is unavailable."})

    result = await _by_name(tools, "show_spending_breakdown").ainvoke({})

    assert result == {"error": "Backend is unavailable."}
    assert sink == []


@pytest.mark.asyncio
async def test_display_tool_reports_gap_when_dependency_missing():
    """A caller supplying a partial transaction-tool set still gets buildable
    display tools — they report the gap at call time instead of exploding."""
    tools, sink = make_widget_tools(_USER_ID, [])

    result = await _by_name(tools, "show_spending_breakdown").ainvoke({})

    assert "error" in result
    assert sink == []


# --------------------------------------------------------------------------
# show_transactions
# --------------------------------------------------------------------------


def _row(txn_id, *, txn_type="debit", currency="EGP", merchant="Carrefour"):
    return {
        "id": str(txn_id),
        "date": "2026-07-14",
        "amount": 340.25,
        "currency": currency,
        "transaction_type": txn_type,
        "merchant": merchant,
        "category": "groceries",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("txn_type", "expected"),
    [
        ("credit", "income"),
        ("debit", "expense"),
        # The mapping mirrors the Django backend's TransactionFilterSet:
        # expense is debit + fee + transfer, not just debit.
        ("fee", "expense"),
        ("transfer", "expense"),
    ],
)
async def test_transactions_map_type_to_income_or_expense(txn_type, expected):
    tools, sink = _tools(transactions=[_row(uuid.uuid4(), txn_type=txn_type)])

    await _by_name(tools, "show_transactions").ainvoke({})

    assert sink[-1].payload.transactions[0].type == expected


@pytest.mark.asyncio
async def test_transactions_builds_typed_widget():
    txn_id = uuid.uuid4()
    tools, sink = _tools(transactions=[_row(txn_id)])

    result = await _by_name(tools, "show_transactions").ainvoke({"limit": 5})

    assert result["shown"] is True
    widget = sink[-1]
    assert isinstance(widget, TransactionsListWidget)
    assert widget.type == "transactions_list"
    item = widget.payload.transactions[0]
    assert item.id == txn_id
    assert item.title == "Carrefour"
    assert item.category == "groceries"
    # The backend stores a date, never a datetime — see decision 6 in the plan.
    assert item.date == datetime.date(2026, 7, 14)


@pytest.mark.asyncio
async def test_transactions_keeps_single_currency():
    tools, sink = _tools(
        transactions=[
            _row(uuid.uuid4(), currency="EGP"),
            _row(uuid.uuid4(), currency="EGP"),
            _row(uuid.uuid4(), currency="USD"),
        ]
    )

    await _by_name(tools, "show_transactions").ainvoke({})

    payload = sink[-1].payload
    assert payload.currency == "EGP"
    assert len(payload.transactions) == 2


@pytest.mark.asyncio
async def test_transactions_emits_no_widget_when_empty():
    tools, sink = _tools(transactions=[])

    result = await _by_name(tools, "show_transactions").ainvoke({})

    assert result["shown"] is False
    assert sink == []


# --------------------------------------------------------------------------
# show_savings_projection
# --------------------------------------------------------------------------


def _patch_planner_context(monkeypatch, context):
    async def _fake(user_id):
        return context

    monkeypatch.setattr("app.features.plan.context.derive_planner_context", _fake)


def _patch_current_balance(monkeypatch, balance):
    async def _fake(user_id, currency=None):
        if balance is None:
            return []
        return [
            {
                "currency": currency or "EGP",
                "current_balance": balance,
                "accounts": [],
            }
        ]

    monkeypatch.setattr("app.tools.widgets.calculate_current_balances", _fake)


@pytest.mark.asyncio
async def test_savings_projection_uses_live_current_balance(monkeypatch):
    _patch_planner_context(
        monkeypatch,
        {"currency": "EGP", "avg_monthly_income": 12000.0, "avg_monthly_recurring_expense": 8500.0},
    )
    _patch_current_balance(monkeypatch, 48200.0)

    tools, sink = _tools()
    result = await _by_name(tools, "show_savings_projection").ainvoke({})

    assert result["shown"] is True
    widget = sink[-1]
    assert isinstance(widget, SavingsSliderWidget)
    assert widget.type == "savings_slider"
    assert widget.payload.currency == "EGP"
    assert widget.payload.current_balance == pytest.approx(48200.0)
    # income - recurring expense, never a guessed rule of thumb.
    assert widget.payload.default_monthly_savings == pytest.approx(3500.0)


@pytest.mark.asyncio
async def test_savings_projection_uses_balance_total_across_accounts(monkeypatch):
    _patch_planner_context(
        monkeypatch,
        {"currency": "EGP", "avg_monthly_income": 5000.0, "avg_monthly_recurring_expense": 1000.0},
    )
    _patch_current_balance(monkeypatch, 2000.0)

    tools, sink = _tools()
    await _by_name(tools, "show_savings_projection").ainvoke({})

    assert sink[-1].payload.current_balance == pytest.approx(2000.0)


@pytest.mark.asyncio
async def test_savings_projection_emits_no_widget_without_any_balance(monkeypatch):
    _patch_planner_context(
        monkeypatch,
        {"currency": "EGP", "avg_monthly_income": 5000.0, "avg_monthly_recurring_expense": 1000.0},
    )
    _patch_current_balance(monkeypatch, None)

    tools, sink = _tools()
    result = await _by_name(tools, "show_savings_projection").ainvoke({})

    assert result["shown"] is False
    assert "balance" in result["reason"].lower()
    assert sink == []


@pytest.mark.asyncio
async def test_savings_projection_emits_no_widget_without_income_signal(monkeypatch):
    _patch_planner_context(
        monkeypatch,
        {"currency": "EGP", "avg_monthly_income": None, "avg_monthly_recurring_expense": None},
    )
    _patch_current_balance(monkeypatch, 48200.0)

    tools, sink = _tools()
    result = await _by_name(tools, "show_savings_projection").ainvoke({})

    assert result["shown"] is False
    assert sink == []


@pytest.mark.asyncio
async def test_savings_projection_emits_no_widget_without_currency(monkeypatch):
    _patch_planner_context(monkeypatch, {"currency": None})

    tools, sink = _tools()
    result = await _by_name(tools, "show_savings_projection").ainvoke({})

    assert result["shown"] is False
    assert sink == []


@pytest.mark.asyncio
async def test_savings_projection_never_goes_negative(monkeypatch):
    """Spending more than you earn is a real state; it must clamp to 0 rather
    than hand the slider a negative starting position."""
    _patch_planner_context(
        monkeypatch,
        {"currency": "EGP", "avg_monthly_income": 1000.0, "avg_monthly_recurring_expense": 4000.0},
    )
    _patch_current_balance(monkeypatch, 500.0)

    tools, sink = _tools()
    await _by_name(tools, "show_savings_projection").ainvoke({})

    assert sink[-1].payload.default_monthly_savings == 0.0


@pytest.mark.asyncio
async def test_savings_projection_reports_backend_failure(monkeypatch):
    _patch_planner_context(
        monkeypatch,
        {"currency": "EGP", "avg_monthly_income": 5000.0, "avg_monthly_recurring_expense": 1000.0},
    )

    async def _boom(user_id, currency=None):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.tools.widgets.calculate_current_balances", _boom)

    tools, sink = _tools()
    result = await _by_name(tools, "show_savings_projection").ainvoke({})

    assert "error" in result
    assert sink == []
