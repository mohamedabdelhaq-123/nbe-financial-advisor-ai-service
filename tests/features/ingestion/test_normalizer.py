"""Unit tests for chunked LangGraph extraction and duplicate matching (US1/US2)."""

import asyncio
import datetime
import decimal
import uuid

import pytest

from app.features.ingestion.normalizer import (
    ExtractedStatement,
    ExtractedTransaction,
    LangGraphNormalizerClient,
    MockNormalizerClient,
    _split_into_chunks,
    _split_table_entry,
    find_duplicate,
    get_normalizer_client,
)


def _txn_row(**overrides) -> dict:
    """A `Transactions` row dict with every NOT NULL column filled.

    The generated `Transaction` model declares no Python-side default for
    `is_recurring`/`source`/`created_at`, so SQLAlchemy's ORM sends explicit
    NULL for them when unset rather than deferring to the DB's DEFAULT
    clause — every caller must supply a full row.
    """
    row = {
        "is_recurring": False,
        "source": "statement",
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    }
    row.update(overrides)
    return row


def _table_row_html(i: int) -> str:
    return f"<tr><td>2026-01-{i:02d}</td><td>Merchant {i}</td><td>{i}.00</td></tr>"


# ---------------------------------------------------------------------------
# Chunking — real HTML parsing (BeautifulSoup), not regex
# ---------------------------------------------------------------------------


def test_split_into_chunks_no_content_falls_back_to_markdown():
    chunks = _split_into_chunks(content_list=[], markdown="some statement text")
    assert chunks == [[{"type": "text", "text": "some statement text"}]]


def test_split_into_chunks_nothing_at_all_returns_no_chunks():
    assert _split_into_chunks(content_list=[], markdown="") == []
    assert _split_into_chunks(content_list=[], markdown="   ") == []


def test_split_into_chunks_small_content_stays_in_one_chunk():
    content_list = [
        {"type": "text", "text": "header"},
        {"type": "table", "table_body": "<table><tr><td>small</td></tr></table>"},
    ]
    chunks = _split_into_chunks(content_list, markdown="", max_chars=3000)
    assert len(chunks) == 1
    assert chunks[0] == content_list


def test_split_table_entry_preserves_every_row_across_batches():
    rows_html = "".join(_table_row_html(i) for i in range(1, 61))
    entry = {"type": "table", "table_body": f"<table>{rows_html}</table>", "page_idx": 0}

    batches = _split_table_entry(entry, max_chars=500)

    assert len(batches) > 1, "expected the oversized table to actually split"
    for batch in batches:
        assert batch["type"] == "table"
        assert batch["page_idx"] == 0  # non-table_body fields preserved
    combined = "".join(b["table_body"] for b in batches)
    for i in range(1, 61):
        assert f"Merchant {i}<" in combined


def test_split_into_chunks_oversized_table_splits_and_preserves_all_rows():
    rows_html = "".join(_table_row_html(i) for i in range(1, 61))
    content_list = [
        {"type": "text", "text": "Bank Statement"},
        {"type": "table", "table_body": f"<table>{rows_html}</table>"},
    ]

    chunks = _split_into_chunks(content_list, markdown="", max_chars=500)

    assert len(chunks) > 1
    combined = "".join(
        entry.get("table_body", "") for chunk in chunks for entry in chunk if "table_body" in entry
    )
    for i in range(1, 61):
        assert f"Merchant {i}<" in combined


# ---------------------------------------------------------------------------
# LangGraphNormalizerClient — sequential per-chunk extraction + aggregation
# (LLM call mocked at the get_chat_model() seam; no network call)
# ---------------------------------------------------------------------------


class _FakeStructuredLLM:
    def __init__(self, results: list[ExtractedStatement]):
        self._results = list(results)
        self.calls = 0

    async def ainvoke(self, prompt):
        self.calls += 1
        return self._results.pop(0)

    def with_retry(self, **kwargs):
        return self


class _FakeChatModel:
    def __init__(self, results: list[ExtractedStatement]):
        self._llm = _FakeStructuredLLM(results)

    def with_structured_output(self, schema):
        return self._llm


def _patch_chat_model(monkeypatch, results: list[ExtractedStatement]):
    fake = _FakeChatModel(results)
    monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: fake)
    return fake


@pytest.mark.asyncio
async def test_langgraph_client_single_chunk_returns_extracted_transactions(monkeypatch):
    _patch_chat_model(
        monkeypatch,
        [
            ExtractedStatement(
                bank_name="Test Bank",
                account_hint="****1234",
                transactions=[
                    ExtractedTransaction(
                        transaction_date="2026-05-01",
                        merchant_raw="Carrefour",
                        ai_description="A grocery purchase at a Carrefour supermarket location.",
                        category="groceries",
                        amount=100.5,
                        transaction_type="debit",
                    )
                ],
            )
        ],
    )

    client = LangGraphNormalizerClient()
    normalized, model_used = await client.normalize(
        content_list=[{"type": "text", "text": "small"}],
        markdown="",
        known_categories=["groceries"],
    )

    assert normalized["bank_name"] == "Test Bank"
    assert normalized["account_hint"] == "****1234"
    assert len(normalized["transactions"]) == 1
    assert normalized["transactions"][0]["merchant_raw"] == "Carrefour"
    assert model_used


@pytest.mark.asyncio
async def test_langgraph_client_aggregates_transactions_across_multiple_chunks(monkeypatch):
    # Two oversized text entries guarantee exactly 2 chunks regardless of the
    # exact _MAX_CHUNK_CHARS tuning: packing is greedy, so a new chunk starts
    # once the running total would exceed the budget, and each entry alone
    # already exceeds it.
    content_list = [
        {"type": "text", "text": "A" * 2000},
        {"type": "text", "text": "B" * 2000},
    ]

    fake = _patch_chat_model(
        monkeypatch,
        [
            ExtractedStatement(
                bank_name="Test Bank",
                transactions=[
                    ExtractedTransaction(
                        transaction_date="2026-01-01",
                        merchant_raw="Chunk 1 txn",
                        ai_description="A debit transaction found in the first chunk of content.",
                        category="other",
                        amount=1.0,
                        transaction_type="debit",
                    )
                ],
            ),
            ExtractedStatement(
                account_hint="****9999",
                transactions=[
                    ExtractedTransaction(
                        transaction_date="2026-01-02",
                        merchant_raw="Chunk 2 txn",
                        ai_description="A credit transaction found in the second chunk of content.",
                        category="other",
                        amount=2.0,
                        transaction_type="credit",
                    )
                ],
            ),
        ],
    )

    client = LangGraphNormalizerClient()
    normalized, _ = await client.normalize(content_list, markdown="", known_categories=[])

    assert fake._llm.calls == 2, "expected one sequential LLM call per chunk"
    assert normalized["bank_name"] == "Test Bank"
    assert normalized["account_hint"] == "****9999"
    merchants = {t["merchant_raw"] for t in normalized["transactions"]}
    assert merchants == {"Chunk 1 txn", "Chunk 2 txn"}


class _ConcurrencyTrackingLLM:
    """Records peak in-flight calls to prove batch dispatch is concurrent."""

    def __init__(self, results: list[ExtractedStatement]):
        self._results = list(results)
        self.calls = 0
        self._in_flight = 0
        self.peak_in_flight = 0

    async def ainvoke(self, prompt):
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        await asyncio.sleep(0.01)
        self._in_flight -= 1
        self.calls += 1
        return self._results.pop()

    def with_retry(self, **kwargs):
        return self


@pytest.mark.asyncio
async def test_langgraph_client_max_parallel_dispatches_batch_concurrently(monkeypatch):
    import app.features.ingestion.normalizer as normalizer_module

    monkeypatch.setattr(normalizer_module.settings, "normalization_max_parallel_chunks", 3)

    content_list = [
        {"type": "text", "text": "A" * 2500},
        {"type": "text", "text": "B" * 2500},
        {"type": "text", "text": "C" * 2500},
    ]
    tracking_llm = _ConcurrencyTrackingLLM(
        [
            ExtractedStatement(
                transactions=[
                    ExtractedTransaction(
                        transaction_date="2026-01-01",
                        merchant_raw=f"txn-{i}",
                        ai_description=f"A debit transaction numbered {i} for concurrency testing.",
                        category="other",
                        amount=1.0,
                        transaction_type="debit",
                    )
                ]
            )
            for i in range(3)
        ]
    )

    class _TrackingChatModel:
        def with_structured_output(self, schema):
            return tracking_llm

    monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: _TrackingChatModel())

    client = LangGraphNormalizerClient()
    normalized, _ = await client.normalize(content_list, markdown="", known_categories=[])

    assert tracking_llm.calls == 3
    assert tracking_llm.peak_in_flight == 3, "expected all 3 chunks dispatched concurrently"
    assert len(normalized["transactions"]) == 3


@pytest.mark.asyncio
async def test_langgraph_client_no_content_returns_empty_without_calling_llm(monkeypatch):
    fake = _patch_chat_model(monkeypatch, [])

    client = LangGraphNormalizerClient()
    normalized, _ = await client.normalize(content_list=[], markdown="", known_categories=[])

    assert normalized == {"bank_name": None, "account_hint": None, "transactions": []}
    assert fake._llm.calls == 0


@pytest.mark.asyncio
async def test_langgraph_client_amount_normalized_to_positive(monkeypatch):
    _patch_chat_model(
        monkeypatch,
        [
            ExtractedStatement(
                transactions=[
                    ExtractedTransaction(
                        transaction_date="2026-05-01",
                        merchant_raw="Carrefour",
                        ai_description="A grocery purchase at a Carrefour supermarket location.",
                        category="groceries",
                        amount=-1234.56,
                        transaction_type="debit",
                    )
                ]
            )
        ],
    )

    client = LangGraphNormalizerClient()
    normalized, _ = await client.normalize(
        content_list=[{"type": "text", "text": "x"}], markdown="", known_categories=[]
    )

    assert normalized["transactions"][0]["amount"] == 1234.56


# ---------------------------------------------------------------------------
# MockNormalizerClient / get_normalizer_client() factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_normalizer_client_with_content_returns_deterministic_result():
    parsed, model_used = await MockNormalizerClient().normalize(
        content_list=[{"type": "text", "text": "some statement content"}],
        markdown="# Statement\nsome text",
        known_categories=[],
    )

    assert parsed["transactions"], "expected at least one mock transaction"
    txn = parsed["transactions"][0]
    assert txn["transaction_date"]
    assert txn["amount"] is not None
    assert txn["ai_description"]
    assert model_used


@pytest.mark.asyncio
async def test_mock_normalizer_client_empty_content_returns_no_transactions():
    parsed, _ = await MockNormalizerClient().normalize(
        content_list=[], markdown="", known_categories=[]
    )

    assert parsed["transactions"] == []
    assert parsed["bank_name"] is None
    assert parsed["account_hint"] is None


def test_get_normalizer_client_returns_mock_when_use_mock_llm(monkeypatch):
    # Patched on the normalizer module's own `settings` reference, not
    # `app.core.config.settings` — `tests/core/test_config.py` reloads that
    # module elsewhere in the suite, which rebinds it to a new object that
    # normalizer.py (imported before the reload) no longer shares.
    import app.features.ingestion.normalizer as normalizer_module

    monkeypatch.setattr(normalizer_module.settings, "use_mock_llm", True)
    assert isinstance(get_normalizer_client(), MockNormalizerClient)


def test_get_normalizer_client_returns_langgraph_when_not_mock(monkeypatch):
    import app.features.ingestion.normalizer as normalizer_module

    monkeypatch.setattr(normalizer_module.settings, "use_mock_llm", False)
    assert isinstance(get_normalizer_client(), LangGraphNormalizerClient)


# ---------------------------------------------------------------------------
# US2 — duplicate matching against a real (Testcontainers) backend-shaped table
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_duplicate_matches_exact_amount_within_window(own_pg, mock_backend_session):
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    existing_id = uuid.uuid4()

    await mock_backend_session(
        [
            _txn_row(
                id=existing_id,
                transaction_date=datetime.date(2026, 5, 1),
                amount=decimal.Decimal("100.50"),
                currency="EGP",
                account_id=account_id,
                user_id=user_id,
                merchant_raw="Carrefour",
            )
        ]
    )

    async with own_pg() as session:
        result = await find_duplicate(
            session, user_id, datetime.date(2026, 5, 2), decimal.Decimal("100.50")
        )

    assert result == str(existing_id)


@pytest.mark.asyncio
async def test_find_duplicate_returns_closest_by_date_when_multiple_match(
    own_pg, mock_backend_session
):
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    far_id = uuid.uuid4()
    close_id = uuid.uuid4()

    await mock_backend_session(
        [
            _txn_row(
                id=far_id,
                transaction_date=datetime.date(2026, 4, 29),
                amount=decimal.Decimal("75.00"),
                currency="EGP",
                account_id=account_id,
                user_id=user_id,
                merchant_raw="Shop A",
            ),
            _txn_row(
                id=close_id,
                transaction_date=datetime.date(2026, 5, 2),
                amount=decimal.Decimal("75.00"),
                currency="EGP",
                account_id=account_id,
                user_id=user_id,
                merchant_raw="Shop B",
            ),
        ]
    )

    async with own_pg() as session:
        result = await find_duplicate(
            session, user_id, datetime.date(2026, 5, 1), decimal.Decimal("75.00")
        )

    assert result == str(close_id)


@pytest.mark.asyncio
async def test_find_duplicate_returns_none_when_no_match(own_pg, mock_backend_session):
    user_id = uuid.uuid4()

    await mock_backend_session([])

    async with own_pg() as session:
        result = await find_duplicate(
            session, user_id, datetime.date(2026, 5, 1), decimal.Decimal("42.00")
        )

    assert result is None
