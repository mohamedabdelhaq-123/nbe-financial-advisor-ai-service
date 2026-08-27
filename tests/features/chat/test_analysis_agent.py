"""US1 Unit test: Analysis agent — grounded data references."""

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from app.core.config import settings
from app.features.chat.agents.analysis import analysis_node
from app.features.chat.schemas import Reference


@pytest.mark.asyncio
async def test_analysis_node_returns_references(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    transactions = [
        type(
            "Txn",
            (),
            {
                "id": f"t{i}",
                "amount": f"{50 + i * 20}.00",
                "merchant_raw": f"Store {i}",
                # `category` is a relationship on the real model — resolves to an
                # object with `.name`, not a bare string. See analysis_node's
                # `txn.category.name if txn.category else "uncategorized"`.
                "category": SimpleNamespace(name="food"),
            },
        )()
        for i in range(1, 4)
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = transactions

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.close = AsyncMock()

    async def _mock_gen():
        yield mock_session

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    state = {
        "messages": [],
        "user_id": uuid.UUID("70b8d118-9b58-45ab-a8ad-4af9ce9105df"),
        "user_context": None,
        "intent": "analysis",
    }

    result = await analysis_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0
    assert "Store 1" in result["messages"][0].content

    # FR-006/FR-007: every reference is a typed Reference with target_type == "transaction".
    refs = result["message_references"]
    assert len(refs) == len(transactions)
    assert all(isinstance(r, Reference) for r in refs)
    assert all(r.target_type == "transaction" for r in refs)
    assert all(r.target_id == str(txn.id) for r, txn in zip(refs, transactions, strict=True))


class _ResolvedCategory:
    """Stands in for the real `Categories` row `Transaction.category` resolves to."""

    def __init__(self, name: str):
        self.name = name


class _LazyCategoryTxn:
    """Mimics a real SQLAlchemy `Transactions` row where `category` is a
    relationship, not a plain column: accessing it raises once the owning
    session has closed — the same failure mode as SQLAlchemy's lazy loader
    under AsyncSession (DetachedInstanceError, or MissingGreenlet if the
    load is attempted outside a greenlet context at all)."""

    def __init__(self, id_: str, amount: str, merchant_raw: str, session_state: dict):
        self.id = id_
        self.amount = amount
        self.merchant_raw = merchant_raw
        self._session_state = session_state

    @property
    def category(self):
        if self._session_state["closed"]:
            raise RuntimeError("simulated: relationship access outside the session")
        return _ResolvedCategory("food")


@pytest.mark.asyncio
async def test_analysis_node_reads_lazy_attributes_before_session_closes(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    # Regression test: analysis_node used to build `lines`/`references` *after*
    # the `async for session in get_backend_session()` block, so touching a
    # lazy-loaded attribute (like the real `category` relationship) there hit
    # DetachedInstanceError — silently swallowed into "Backend is unavailable".
    session_state = {"closed": False}
    transactions = [
        _LazyCategoryTxn(f"t{i}", f"{50 + i * 20}.00", f"Store {i}", session_state)
        for i in range(1, 4)
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = transactions

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _mock_gen():
        try:
            yield mock_session
        finally:
            session_state["closed"] = True

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    state = {
        "messages": [],
        "user_id": uuid.UUID("70b8d118-9b58-45ab-a8ad-4af9ce9105df"),
        "user_context": None,
        "intent": "analysis",
    }

    result = await analysis_node(state)

    # A regression would fall into the except-Exception branch and return
    # this text instead.
    assert "Backend is unavailable" not in result["messages"][0].content
    assert len(result["message_references"]) == len(transactions)

    # The analysis agent reports what the user already spent — a statement of
    # fact, not advice — so it must NOT carry the advice disclaimer. That is
    # reserved for the planner and the recommendation agent (guards.py's
    # with_disclaimer docstring).
    from app.features.chat.guards import DISCLAIMER

    assert DISCLAIMER not in result["messages"][0].content


@pytest.mark.asyncio
async def test_analysis_node_no_data(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.close = AsyncMock()

    async def _mock_gen():
        yield mock_session

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    state = {
        "messages": [],
        "user_id": uuid.UUID("35949f20-c6b5-4889-a37d-a09ef0af6b1e"),
        "user_context": None,
        "intent": "analysis",
    }

    result = await analysis_node(state)
    assert "messages" in result
    no_data_found = any(
        "don't have" in m.content.lower() or "no data" in m.content.lower()
        for m in result["messages"]
    )
    assert no_data_found


# ── _agentic_analysis: the real (non-mock) tool-calling loop ────────────────
# Unlike everything above (which exercises _mock_analysis, the only branch
# the rest of the suite runs under AI_SERVICE_CHAT_MODEL__USE_MOCK=1), these
# force settings.chat_model.use_mock=False for the duration of each test to
# reach _agentic_analysis directly, with a fake chat model at the
# get_chat_model() seam — same technique as test_graph.py's
# test_general_node_sends_a_system_prompt_when_not_mocked.


class _FakeToolModel:
    """A minimal stand-in for a tool-calling chat model: `.bind_tools()`
    returns itself (so the real `model_with_tools = base_model.bind_tools(
    tools)` call in _agentic_analysis is a no-op), and `.ainvoke()` replays
    pre-scripted responses in order — one per loop iteration."""

    def __init__(self, responses):
        self._responses = iter(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return next(self._responses)


@pytest.mark.asyncio
async def test_agentic_analysis_happy_path_tool_call_round_trip(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    tool_call_msg = AIMessage(
        content="", tool_calls=[{"name": "get_transactions", "args": {}, "id": "call_1"}]
    )
    final_msg = AIMessage(content="You spent 400 EGP on lifestyle this month.")
    monkeypatch.setattr(
        "app.core.llm.get_chat_model", lambda **kwargs: _FakeToolModel([tool_call_msg, final_msg])
    )

    @tool
    async def get_transactions(**kwargs) -> dict:
        """Fake get_transactions returning one canned row."""
        return {
            "count": 1,
            "transactions": [{"id": "t1", "amount": 400.0, "category": "lifestyle"}],
        }

    monkeypatch.setattr(
        "app.tools.transactions.make_transaction_tools", lambda user_id: [get_transactions]
    )

    state = {
        "messages": [HumanMessage(content="what did I spend the most on this month?")],
        "user_id": uuid.uuid4(),
        "user_context": None,
        "intent": "analysis",
    }
    result = await analysis_node(state)

    assert result["messages"][-1].content == "You spent 400 EGP on lifestyle this month."
    assert len(result["message_references"]) == 1
    assert result["message_references"][0].target_id == "t1"


@pytest.mark.asyncio
async def test_agentic_analysis_llm_failure_gets_honest_fallback_message(monkeypatch):
    # Regression guard for the actual bug: the outer except used to claim
    # "Backend is unavailable" for ANY failure in this loop, even though the
    # tools themselves never raise up to here — in practice this catch is
    # almost always an LLM-call failure, not a DB outage.
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    class _RaisingModel:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            raise RuntimeError("simulated OpenRouter timeout")

    monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: _RaisingModel())

    state = {
        "messages": [HumanMessage(content="what did i spend on the most last month?")],
        "user_id": uuid.uuid4(),
        "user_context": None,
        "intent": "analysis",
    }
    result = await analysis_node(state)

    content = result["messages"][0].content
    assert content == "Sorry, I couldn't finish analyzing that just now — please try again."
    assert "Backend is unavailable" not in content


@pytest.mark.asyncio
async def test_agentic_analysis_zero_rows_gets_plain_reply_not_generic_fallback(monkeypatch):
    # The exact scenario from the reported bug: a date range with no
    # matching transactions must not be misrouted into the except block —
    # the tools return an empty-but-successful result, and the model is
    # expected to say so plainly (per the system prompt's own instruction).
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    tool_call_msg = AIMessage(
        content="", tool_calls=[{"name": "get_transactions", "args": {}, "id": "call_1"}]
    )
    final_msg = AIMessage(content="You had no transactions last month.")
    monkeypatch.setattr(
        "app.core.llm.get_chat_model", lambda **kwargs: _FakeToolModel([tool_call_msg, final_msg])
    )

    @tool
    async def get_transactions(**kwargs) -> dict:
        """Fake get_transactions returning zero rows."""
        return {"count": 0, "transactions": []}

    monkeypatch.setattr(
        "app.tools.transactions.make_transaction_tools", lambda user_id: [get_transactions]
    )

    state = {
        "messages": [HumanMessage(content="what did i spend on the most last month?")],
        "user_id": uuid.uuid4(),
        "user_context": None,
        "intent": "analysis",
    }
    result = await analysis_node(state)

    content = result["messages"][-1].content
    assert content == "You had no transactions last month."
    assert "Backend is unavailable" not in content
    assert result["message_references"] == []


@pytest.mark.asyncio
async def test_agentic_analysis_attaches_widget_from_display_tool(monkeypatch):
    """The model chooses to call a display tool; the widget it produces reaches
    the node's return value alongside the prose reply."""
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "show_spending_breakdown",
                "args": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
                "id": "call_1",
            }
        ],
    )
    final_msg = AIMessage(content="Housing was your biggest expense at 750 EGP.")
    monkeypatch.setattr(
        "app.core.llm.get_chat_model", lambda **kwargs: _FakeToolModel([tool_call_msg, final_msg])
    )

    @tool
    async def compute_aggregate(**kwargs) -> dict:
        """Fake aggregate broken out by category."""
        return {
            "groups": [
                {"currency": "EGP", "category": "housing", "value": 750.0},
                {"currency": "EGP", "category": "groceries", "value": 250.0},
            ]
        }

    monkeypatch.setattr(
        "app.tools.transactions.make_transaction_tools", lambda user_id: [compute_aggregate]
    )

    state = {
        "messages": [HumanMessage(content="where did my money go last month?")],
        "user_id": uuid.uuid4(),
        "user_context": None,
        "intent": "analysis",
    }
    result = await analysis_node(state)

    from app.features.chat.schemas import SpendingBreakdownWidget

    widget = result["widget"]
    assert isinstance(widget, SpendingBreakdownWidget)
    assert widget.payload.currency == "EGP"
    assert widget.payload.total == pytest.approx(1000.0)
    # The prose answer still stands on its own — the widget supplements it.
    assert result["messages"][-1].content == "Housing was your biggest expense at 750 EGP."


@pytest.mark.asyncio
async def test_agentic_analysis_widget_is_none_when_no_display_tool_called(monkeypatch):
    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    monkeypatch.setattr(
        "app.core.llm.get_chat_model",
        lambda **kwargs: _FakeToolModel([AIMessage(content="You spent 400 EGP.")]),
    )
    monkeypatch.setattr("app.tools.transactions.make_transaction_tools", lambda user_id: [])

    state = {
        "messages": [HumanMessage(content="how much did I spend?")],
        "user_id": uuid.uuid4(),
        "user_context": None,
        "intent": "analysis",
    }
    result = await analysis_node(state)

    assert result["widget"] is None


@pytest.mark.asyncio
async def test_mock_analysis_emits_transactions_list_widget(monkeypatch):
    """Mock mode gives a frontend running fully offline something to render."""
    import datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    txn_id = uuid.uuid4()
    transactions = [
        SimpleNamespace(
            id=txn_id,
            amount="340.25",
            currency="EGP",
            transaction_date=datetime.date(2026, 7, 14),
            transaction_type="debit",
            merchant_raw="Carrefour",
            merchant_normalized=None,
            category=SimpleNamespace(name="groceries"),
        )
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = transactions
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _mock_gen():
        yield mock_session

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    state = {
        "messages": [],
        "user_id": uuid.uuid4(),
        "user_context": None,
        "intent": "analysis",
    }
    result = await analysis_node(state)

    from app.features.chat.schemas import TransactionsListWidget

    widget = result["widget"]
    assert isinstance(widget, TransactionsListWidget)
    item = widget.payload.transactions[0]
    assert item.id == txn_id
    assert item.title == "Carrefour"
    assert item.type == "expense"
    assert item.date == datetime.date(2026, 7, 14)


@pytest.mark.asyncio
async def test_mock_analysis_skips_widget_for_incomplete_rows(monkeypatch):
    """Minimal test fixtures (no currency/date, non-UUID ids) must not turn a
    chat turn into a failure — the widget is simply omitted."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    transactions = [
        SimpleNamespace(
            id="t1", amount="50.00", merchant_raw="Store", category=SimpleNamespace(name="food")
        )
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = transactions
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _mock_gen():
        yield mock_session

    monkeypatch.setattr("app.backend_db.get_backend_session", _mock_gen)

    result = await analysis_node(
        {
            "messages": [],
            "user_id": uuid.uuid4(),
            "user_context": None,
            "intent": "analysis",
        }
    )

    assert result["widget"] is None
    assert len(result["message_references"]) == 1
