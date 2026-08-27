"""Unit tests for app.tools.transactions.

Regression coverage for a real failure observed against the configured
OpenRouter model (nvidia/nemotron-3-nano-30b-a3b:free): it fills every
optional plain-`str` argument (category, currency) with the literal string
"none" instead of omitting it. Unlike a `Literal`-typed argument, Pydantic
doesn't reject an arbitrary string there, so a naive filter would silently
build `WHERE currency = 'NONE'` — matching zero real rows instead of raising
an error. `_clean_optional` normalizes that sentinel back to None before it
reaches the query.
"""

import datetime
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.transactions import _clean_optional, make_transaction_tools


@pytest.mark.parametrize("raw", ["none", "None", "NONE", "null", "", "  none  "])
def test_clean_optional_normalizes_sentinel_strings(raw):
    assert _clean_optional(raw) is None


@pytest.mark.parametrize("raw", ["EGP", "groceries", "usd"])
def test_clean_optional_passes_through_real_values(raw):
    assert _clean_optional(raw) == raw


@pytest.mark.asyncio
async def test_get_transactions_ignores_none_sentinel_currency_and_category(monkeypatch):
    captured = {}

    async def _fake_get_backend_session():
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        async def _execute(stmt):
            captured["stmt"] = stmt
            return mock_result

        session = MagicMock()
        session.execute = _execute
        yield session

    monkeypatch.setattr("app.backend_db.get_backend_session", _fake_get_backend_session)

    tools = make_transaction_tools(uuid.uuid4())
    get_transactions = next(t for t in tools if t.name == "get_transactions")

    await get_transactions.ainvoke({"currency": "none", "category": "NULL"})

    # `select(Transaction)` always lists every column, including `currency`,
    # so the meaningful check is that no WHERE comparison or category JOIN
    # was added — not that the word "currency" is absent altogether.
    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "transactions.currency =" not in sql.lower()
    assert "join" not in sql.lower()
    assert "'none'" not in sql.lower()


@pytest.mark.asyncio
async def test_get_transactions_applies_real_currency_filter(monkeypatch):
    captured = {}

    async def _fake_get_backend_session():
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        async def _execute(stmt):
            captured["stmt"] = stmt
            return mock_result

        session = MagicMock()
        session.execute = _execute
        yield session

    monkeypatch.setattr("app.backend_db.get_backend_session", _fake_get_backend_session)

    tools = make_transaction_tools(uuid.uuid4())
    get_transactions = next(t for t in tools if t.name == "get_transactions")

    await get_transactions.ainvoke({"currency": "egp"})

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "'EGP'" in sql


async def _capture_stmt(monkeypatch):
    captured = {}

    async def _fake_get_backend_session():
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []

        async def _execute(stmt):
            captured["stmt"] = stmt
            return mock_result

        session = MagicMock()
        session.execute = _execute
        yield session

    monkeypatch.setattr("app.backend_db.get_backend_session", _fake_get_backend_session)
    return captured


@pytest.mark.asyncio
async def test_get_transactions_applies_is_recurring_filter(monkeypatch):
    captured = await _capture_stmt(monkeypatch)
    tools = make_transaction_tools(uuid.uuid4())
    get_transactions = next(t for t in tools if t.name == "get_transactions")

    await get_transactions.ainvoke({"is_recurring": True})

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "transactions.is_recurring = true" in sql.lower()


@pytest.mark.asyncio
async def test_get_transactions_omits_is_recurring_filter_when_unset(monkeypatch):
    captured = await _capture_stmt(monkeypatch)
    tools = make_transaction_tools(uuid.uuid4())
    get_transactions = next(t for t in tools if t.name == "get_transactions")

    await get_transactions.ainvoke({})

    # `select(Transaction)` always lists every column, including `is_recurring`,
    # so check for the absence of a WHERE comparison, not the bare column name.
    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "transactions.is_recurring =" not in sql.lower()


@pytest.mark.asyncio
async def test_compute_aggregate_applies_is_recurring_filter(monkeypatch):
    captured = await _capture_stmt(monkeypatch)
    tools = make_transaction_tools(uuid.uuid4())
    compute_aggregate = next(t for t in tools if t.name == "compute_aggregate")

    await compute_aggregate.ainvoke({"op": "sum", "is_recurring": False})

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "transactions.is_recurring = false" in sql.lower()


@pytest.mark.asyncio
async def test_compute_aggregate_omits_is_recurring_filter_when_unset(monkeypatch):
    captured = await _capture_stmt(monkeypatch)
    tools = make_transaction_tools(uuid.uuid4())
    compute_aggregate = next(t for t in tools if t.name == "compute_aggregate")

    await compute_aggregate.ainvoke({"op": "sum"})

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "is_recurring" not in sql.lower()


def _fake_transaction(**overrides):
    category = types.SimpleNamespace(name=overrides.pop("category_name", "coffee"))
    defaults = dict(
        id=uuid.uuid4(),
        transaction_date=datetime.date(2026, 8, 1),
        amount=12.5,
        currency="EGP",
        transaction_type="debit",
        merchant_raw="Costa Coffee",
        category=category,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_find_similar_transactions_rejects_empty_query(monkeypatch):
    embed_mock = AsyncMock()
    monkeypatch.setattr("app.features.embed.service.embed_texts", embed_mock)

    tools = make_transaction_tools(uuid.uuid4())
    find_similar = next(t for t in tools if t.name == "find_similar_transactions")

    result = await find_similar.ainvoke({"query": "   "})

    assert "error" in result
    embed_mock.assert_not_called()


@pytest.mark.asyncio
async def test_find_similar_transactions_handles_embed_failure(monkeypatch):
    monkeypatch.setattr(
        "app.features.embed.service.embed_texts",
        AsyncMock(side_effect=RuntimeError("embedding provider down")),
    )

    tools = make_transaction_tools(uuid.uuid4())
    find_similar = next(t for t in tools if t.name == "find_similar_transactions")

    result = await find_similar.ainvoke({"query": "coffee last week"})

    assert "error" in result


@pytest.mark.asyncio
async def test_find_similar_transactions_filters_null_embeddings_and_caps_top_k(monkeypatch):
    monkeypatch.setattr(
        "app.features.embed.service.embed_texts",
        AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
    )
    captured = await _capture_stmt(monkeypatch)

    tools = make_transaction_tools(uuid.uuid4())
    find_similar = next(t for t in tools if t.name == "find_similar_transactions")

    await find_similar.ainvoke({"query": "coffee last week", "top_k": 100})

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "embedding is not null" in sql.lower()
    assert "order by" in sql.lower()
    assert "limit 20" in sql.lower()  # capped, not the requested 100


@pytest.mark.asyncio
async def test_find_similar_transactions_returns_ranked_rows(monkeypatch):
    monkeypatch.setattr(
        "app.features.embed.service.embed_texts",
        AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
    )

    fake_txn = _fake_transaction()

    async def _fake_get_backend_session():
        mock_result = MagicMock()
        mock_result.all.return_value = [(fake_txn, 0.87)]

        async def _execute(stmt):
            return mock_result

        session = MagicMock()
        session.execute = _execute
        yield session

    monkeypatch.setattr("app.backend_db.get_backend_session", _fake_get_backend_session)

    tools = make_transaction_tools(uuid.uuid4())
    find_similar = next(t for t in tools if t.name == "find_similar_transactions")

    result = await find_similar.ainvoke({"query": "coffee last week"})

    assert result["count"] == 1
    row = result["transactions"][0]
    assert row["merchant"] == "Costa Coffee"
    assert row["category"] == "coffee"
    assert row["similarity"] == pytest.approx(0.87)
