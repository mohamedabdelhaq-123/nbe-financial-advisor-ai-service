"""Unit tests for chunked LangGraph extraction and duplicate matching (US1/US2)."""

import asyncio
import datetime
import decimal
import json
import re
import uuid

import pytest

from app.features.ingestion.normalizer import (
    ChunkedLangGraphNormalizerClient,
    ExtractedStatement,
    ExtractedTransaction,
    MockNormalizerClient,
    _split_into_chunks,
    _split_table_entry,
    find_duplicate,
    get_normalizer_client,
)
from app.features.ingestion.normalizer.agents.chunked_langgraph.prompts import (
    get_normalization_prompt,
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


def test_split_table_entry_preserves_every_row_across_row_capped_portions():
    rows_html = "".join(_table_row_html(i) for i in range(1, 61))
    entry = {"type": "table", "table_body": f"<table>{rows_html}</table>", "page_idx": 0}

    batches = _split_table_entry(entry, max_rows=10)

    assert len(batches) == 6, "60 rows / 10 per portion"
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
# US4 (FR-007/FR-008/FR-009) — row-count-primary chunking
# ---------------------------------------------------------------------------


def _rows_in_chunk(chunk: list[dict]) -> int:
    from bs4 import BeautifulSoup

    return sum(
        len(BeautifulSoup(e.get("table_body") or "", "html.parser").find_all("tr"))
        for e in chunk
        if e.get("type") == "table"
    )


def test_row_based_portioning_packs_stable_row_count_regardless_of_text_length_variance():
    """FR-007 — portion boundaries track row count, not per-row text length."""
    short_rows = "".join(
        f"<tr><td>2026-01-{i:02d}</td><td>M{i}</td><td>{i}.00</td></tr>" for i in range(1, 21)
    )
    long_rows = "".join(
        f"<tr><td>2026-01-{i:02d}</td><td>{'X' * 300}M{i}</td><td>{i}.00</td></tr>"
        for i in range(1, 21)
    )
    short_chunks = _split_into_chunks(
        [{"type": "table", "table_body": f"<table>{short_rows}</table>"}],
        "",
        max_rows=6,
        max_chars=10**9,
    )
    long_chunks = _split_into_chunks(
        [{"type": "table", "table_body": f"<table>{long_rows}</table>"}],
        "",
        max_rows=6,
        max_chars=10**9,
    )

    distribution_short = [_rows_in_chunk(c) for c in short_chunks]
    distribution_long = [_rows_in_chunk(c) for c in long_chunks]
    # 20 rows / 6 per portion -> 6,6,6,2 regardless of how long each row's text is.
    assert distribution_short == [6, 6, 6, 2]
    assert distribution_long == [6, 6, 6, 2]


def test_row_cap_formula_matches_research_specification():
    """FR-007 — max_rows = max(1, floor(0.7 * chunk_max_tokens / est_tokens_per_row))."""
    from app.features.ingestion.normalizer.agents.chunked_langgraph.chunking import _row_cap

    assert _row_cap(4096, 450) == 6  # floor(0.7 * 4096 / 450) = floor(6.37)
    assert _row_cap(5000, 100) == 35  # floor(0.7 * 5000 / 100)
    assert _row_cap(100, 1000) == 1  # floor(0.07) -> clamped to 1 (FR-008)


def test_single_oversized_row_still_produces_nonempty_portion():
    """FR-008 — a single row exceeding the char ceiling isn't dropped."""
    huge_row = f"<tr><td>{'X' * 5000}</td></tr>"
    entry = {"type": "table", "table_body": f"<table>{huge_row}</table>"}

    chunks = _split_into_chunks([entry], "", max_rows=6, max_chars=500)

    assert len(chunks) == 1
    assert len(chunks[0]) == 1  # oversized but present
    assert _rows_in_chunk(chunks[0]) == 1


def test_non_table_entries_pack_under_char_ceiling_uncounted_against_row_cap():
    """FR-007 — non-table entries don't count against the row cap; char ceiling governs."""
    entries = [{"type": "text", "text": f"line number {i}"} for i in range(5)]

    liberal = _split_into_chunks(entries, "", max_rows=1, max_chars=10**9)
    assert len(liberal) == 1, "zero-row entries never trip a max_rows=1 cap"
    assert len(liberal[0]) == 5

    tight = _split_into_chunks(entries, "", max_rows=1, max_chars=20)
    assert len(tight) > 1, "char ceiling still bounds portion size"


@pytest.mark.asyncio
async def test_chunking_strategy_change_preserves_extracted_transaction_set(monkeypatch):
    """SC-005/FR-009 — portioning by row count vs character length yields the
    same set of extracted transactions (a stubbed deterministic LLM extracts one
    transaction per <tr> row it sees)."""
    from bs4 import BeautifulSoup

    import app.features.ingestion.normalizer as normalizer_module

    rows_html = "".join(_table_row_html(i) for i in range(1, 25))  # 24 rows
    content_list = [{"type": "table", "table_body": f"<table>{rows_html}</table>"}]

    class _RowCountingChatModel:
        class _LLM:
            async def ainvoke(self, prompt, config=None):
                rows = BeautifulSoup(prompt, "html.parser").find_all("tr")
                return ExtractedStatement(
                    transactions=[
                        ExtractedTransaction(
                            transaction_date="2026-01-01",
                            merchant_raw=row.get_text(),
                            ai_description="one row",
                            category="other",
                            amount=1.0,
                            transaction_type="debit",
                        )
                        for row in rows
                    ]
                )

            def with_retry(self, **kwargs):
                return self

        def with_structured_output(self, schema):
            return self._LLM()

    async def _run(est_tokens_per_row: int) -> list[str]:
        monkeypatch.setattr(
            normalizer_module.settings.chat_model,
            "normalization_est_tokens_per_row",
            est_tokens_per_row,
        )
        monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: _RowCountingChatModel())
        client = ChunkedLangGraphNormalizerClient()
        normalized, _ = await client.normalize(
            content_list,
            markdown="",
            known_categories=[],
            statement_id="stmt-1",
            ocr_result_id="ocr-1",
        )
        return sorted(t.merchant_raw for t in normalized.transactions)

    row_based = await _run(450)  # max_rows=6 -> 4 portions of 6 rows
    char_based = await _run(1)  # max_rows huge -> table portions by char ceiling only

    expected = sorted(_table_row_html_text(i) for i in range(1, 25))
    assert row_based == char_based == expected


def _table_row_html_text(i: int) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(_table_row_html(i), "html.parser").get_text()


# ---------------------------------------------------------------------------
# ChunkedLangGraphNormalizerClient — sequential per-chunk extraction + aggregation
# (LLM call mocked at the get_chat_model() seam; no network call)
# ---------------------------------------------------------------------------


class _FakeStructuredLLM:
    def __init__(self, results: list[ExtractedStatement]):
        self._results = list(results)
        self.calls = 0

    async def ainvoke(self, prompt, config=None):
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
                account_number="4213010248203200016",
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

    client = ChunkedLangGraphNormalizerClient()
    normalized, model_used = await client.normalize(
        content_list=[{"type": "text", "text": "small"}],
        markdown="",
        known_categories=["groceries"],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )

    assert normalized.bank_name == "Test Bank"
    assert normalized.account_number == "4213010248203200016"
    assert len(normalized.transactions) == 1
    assert normalized.transactions[0].merchant_raw == "Carrefour"
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
                account_number="1002003004005006",
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

    client = ChunkedLangGraphNormalizerClient()
    normalized, _ = await client.normalize(
        content_list,
        markdown="",
        known_categories=[],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )

    assert fake._llm.calls == 2, "expected one sequential LLM call per chunk"
    assert normalized.bank_name == "Test Bank"
    assert normalized.account_number == "1002003004005006"
    merchants = {t.merchant_raw for t in normalized.transactions}
    assert merchants == {"Chunk 1 txn", "Chunk 2 txn"}


class _ConcurrencyTrackingLLM:
    """Records peak in-flight calls to prove batch dispatch is concurrent."""

    def __init__(self, results: list[ExtractedStatement]):
        self._results = list(results)
        self.calls = 0
        self._in_flight = 0
        self.peak_in_flight = 0

    async def ainvoke(self, prompt, config=None):
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

    monkeypatch.setattr(
        normalizer_module.settings.chat_model, "normalization_max_parallel_chunks", 3
    )

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

    client = ChunkedLangGraphNormalizerClient()
    normalized, _ = await client.normalize(
        content_list,
        markdown="",
        known_categories=[],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )

    assert tracking_llm.calls == 3
    assert tracking_llm.peak_in_flight == 3, "expected all 3 chunks dispatched concurrently"
    assert len(normalized.transactions) == 3


@pytest.mark.asyncio
async def test_langgraph_client_no_content_returns_empty_without_calling_llm(monkeypatch):
    fake = _patch_chat_model(monkeypatch, [])

    client = ChunkedLangGraphNormalizerClient()
    normalized, _ = await client.normalize(
        content_list=[],
        markdown="",
        known_categories=[],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )

    assert normalized == ExtractedStatement()
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

    client = ChunkedLangGraphNormalizerClient()
    normalized, _ = await client.normalize(
        content_list=[{"type": "text", "text": "x"}],
        markdown="",
        known_categories=[],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )

    assert normalized.transactions[0].amount == 1234.56


# ---------------------------------------------------------------------------
# MockNormalizerClient / get_normalizer_client() factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_normalizer_client_with_content_returns_deterministic_result():
    parsed, model_used = await MockNormalizerClient().normalize(
        content_list=[{"type": "text", "text": "some statement content"}],
        markdown="# Statement\nsome text",
        known_categories=[],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )

    assert parsed.transactions, "expected at least one mock transaction"
    txn = parsed.transactions[0]
    assert txn.transaction_date
    assert txn.amount is not None
    assert txn.ai_description
    assert model_used


@pytest.mark.asyncio
async def test_mock_normalizer_client_empty_content_returns_no_transactions():
    parsed, _ = await MockNormalizerClient().normalize(
        content_list=[],
        markdown="",
        known_categories=[],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )

    assert parsed.transactions == []
    assert parsed.bank_name is None
    assert parsed.account_number is None


def test_get_normalizer_client_returns_mock_when_use_mock_llm(monkeypatch):
    # Patched on the normalizer module's own `settings` reference, not
    # `app.core.config.settings` — `tests/core/test_config.py` reloads that
    # module elsewhere in the suite, which rebinds it to a new object that
    # normalizer.py (imported before the reload) no longer shares.
    import app.features.ingestion.normalizer as normalizer_module

    monkeypatch.setattr(normalizer_module.settings.chat_model, "use_mock", True)
    assert isinstance(get_normalizer_client(), MockNormalizerClient)


def test_get_normalizer_client_returns_langgraph_when_not_mock(monkeypatch):
    import app.features.ingestion.normalizer as normalizer_module

    monkeypatch.setattr(normalizer_module.settings.chat_model, "use_mock", False)
    assert isinstance(get_normalizer_client(), ChunkedLangGraphNormalizerClient)


def test_get_normalizer_client_dispatches_on_strategy_for_chunked_langgraph(monkeypatch):
    """FR-010/US5 — the real path selects the implementation by strategy."""
    import app.features.ingestion.normalizer as normalizer_module

    monkeypatch.setattr(normalizer_module.settings.chat_model, "use_mock", False)
    monkeypatch.setattr(
        normalizer_module.settings.chat_model, "normalizer_strategy", "chunked_langgraph"
    )
    assert isinstance(get_normalizer_client(), ChunkedLangGraphNormalizerClient)


def test_invalid_normalizer_strategy_rejected_at_config_parse_time():
    """Constitution VII — an invalid strategy is a Literal parse-time failure,
    not a runtime branch in get_normalizer_client()."""
    from pydantic import ValidationError

    from app.core.config import ChatModelSettings

    with pytest.raises(ValidationError):
        ChatModelSettings(normalizer_strategy="not-a-real-strategy")


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


# ---------------------------------------------------------------------------
# Prompt-template golden-string tests (FR-005: byte-for-byte wording preservation)
# ---------------------------------------------------------------------------

_CHUNK = [{"type": "text", "text": "Bank statement line"}]

_GOLDEN_WITH_CATEGORIES = (
    "Extract structured transaction data from this fragment of a bank statement's "
    "OCR output. This may be only part of the full statement — extract only what's "
    "present here.\n\n"
    'Content:\n[{"type": "text", "text": "Bank statement line"}]\n\n'
    "Choose each transaction's category from exactly this list (no other values): "
    "['groceries', 'rent'].\n"
    "transaction_date must be converted to YYYY-MM-DD even if the source uses a "
    "different format (e.g. '30-October-2024' becomes '2024-10-30').\n"
    "Omit any transaction whose date or amount you cannot confidently determine.\n"
    "ai_description must be a verbose, multi-sentence natural-language description of "
    "each transaction — do not just repeat merchant_raw. Explain what the transaction "
    "likely was for and include any other relevant context from this fragment.\n"
    "If bank_name or account_number isn't stated in this fragment, use null — never "
    "a placeholder phrase like 'not mentioned' or 'unknown', and never add bank_name "
    "or account_number as an extra_fields entry (they always belong in the dedicated "
    "top-level fields, never duplicated into extra_fields). Transcribe the account "
    "number exactly as printed in the source — never masked, truncated, or redacted "
    "(copy every digit verbatim).\n"
    "For each transaction, set balance to the running balance stated for that row "
    "(null when the source doesn't state one for it — never guess or carry one "
    "row's balance into another), and set merchant_normalized to a clean, "
    "canonical merchant name distinct from merchant_raw (e.g. 'Carrefour' rather "
    "than a raw POS reference string; null when not confidently determinable). "
    "balance and merchant_normalized never belong in extra_fields.\n"
    "Each key in extra_fields must be unique — do not repeat the same key with a different value."
)

_GOLDEN_WITHOUT_CATEGORIES = (
    "Extract structured transaction data from this fragment of a bank statement's "
    "OCR output. This may be only part of the full statement — extract only what's "
    "present here.\n\n"
    'Content:\n[{"type": "text", "text": "Bank statement line"}]\n\n'
    "transaction_date must be converted to YYYY-MM-DD even if the source uses a "
    "different format (e.g. '30-October-2024' becomes '2024-10-30').\n"
    "Omit any transaction whose date or amount you cannot confidently determine.\n"
    "ai_description must be a verbose, multi-sentence natural-language description of "
    "each transaction — do not just repeat merchant_raw. Explain what the transaction "
    "likely was for and include any other relevant context from this fragment.\n"
    "If bank_name or account_number isn't stated in this fragment, use null — never "
    "a placeholder phrase like 'not mentioned' or 'unknown', and never add bank_name "
    "or account_number as an extra_fields entry (they always belong in the dedicated "
    "top-level fields, never duplicated into extra_fields). Transcribe the account "
    "number exactly as printed in the source — never masked, truncated, or redacted "
    "(copy every digit verbatim).\n"
    "For each transaction, set balance to the running balance stated for that row "
    "(null when the source doesn't state one for it — never guess or carry one "
    "row's balance into another), and set merchant_normalized to a clean, "
    "canonical merchant name distinct from merchant_raw (e.g. 'Carrefour' rather "
    "than a raw POS reference string; null when not confidently determinable). "
    "balance and merchant_normalized never belong in extra_fields.\n"
    "Each key in extra_fields must be unique — do not repeat the same key with a different value."
)


def test_normalization_prompt_matches_hardcoded_output_with_categories():
    """US1 acceptance #1 — template output is byte-for-byte the old hardcoded prompt."""
    rendered = get_normalization_prompt().render(
        chunk=json.dumps(_CHUNK), known_categories=["groceries", "rent"]
    )
    assert rendered == _GOLDEN_WITH_CATEGORIES


def test_normalization_prompt_omits_category_clause_when_none():
    """US1 acceptance #2 — known_categories=None drops the category hint entirely."""
    rendered = get_normalization_prompt().render(chunk=json.dumps(_CHUNK), known_categories=None)
    assert rendered == _GOLDEN_WITHOUT_CATEGORIES
    # The hint clause must be fully absent, not just an empty interpolation.
    assert "Choose each transaction's category" not in rendered


# ---------------------------------------------------------------------------
# US1 (FR-003) — ExtractedTransaction gains balance / merchant_normalized
# ---------------------------------------------------------------------------


def test_extracted_transaction_balance_and_merchant_normalized_round_trip_and_default_none():
    """FR-003 — dedicated optional fields, null when not determinable."""
    with_balance = ExtractedTransaction(
        transaction_date="2026-05-01",
        merchant_raw="Carrefour #abc123",
        ai_description="A grocery purchase at a Carrefour supermarket location.",
        category="groceries",
        amount=100.0,
        transaction_type="debit",
        balance=4809.31,
        merchant_normalized="Carrefour",
    )
    assert with_balance.balance == 4809.31
    assert with_balance.merchant_normalized == "Carrefour"

    plain = ExtractedTransaction(
        transaction_date="2026-05-01",
        merchant_raw="Cash",
        ai_description="A cash withdrawal.",
        category="other",
        amount=5.0,
        transaction_type="debit",
    )
    assert plain.balance is None
    assert plain.merchant_normalized is None


# ---------------------------------------------------------------------------
# US2 (FR-002) — ExtractedStatement.account_number replaces account_hint
# ---------------------------------------------------------------------------


def test_extracted_statement_account_number_round_trips_raw_digits_and_defaults_none():
    """FR-002 — real, unmasked account number; null when not determinable."""
    with_number = ExtractedStatement(bank_name="Test Bank", account_number="4213010248203200016")
    assert with_number.account_number == "4213010248203200016"
    assert not hasattr(with_number, "account_hint"), "old account_hint field is gone"

    plain = ExtractedStatement()
    assert plain.account_number is None
    assert not hasattr(plain, "account_hint")


# ---------------------------------------------------------------------------
# US3 (FR-005/FR-006/FR-009/FR-016) — Send fan-out + max_concurrency graph
# (LLM call mocked at the get_chat_model() seam; no network call)
# ---------------------------------------------------------------------------


class _DeterministicByChunkChatModel:
    """Returns one transaction whose merchant is derived from a `chunk-marker-N`
    token in the prompt, so results are stable regardless of dispatch order."""

    class _LLM:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, prompt, config=None):
            self.calls += 1
            match = re.search(r"chunk-marker-(\d+)", prompt)
            n = int(match.group(1)) if match else 0
            return ExtractedStatement(
                transactions=[
                    ExtractedTransaction(
                        transaction_date="2026-01-01",
                        merchant_raw=f"chunk-{n}",
                        ai_description=f"A transaction extracted from chunk number {n}.",
                        category="other",
                        amount=float(n),
                        transaction_type="debit",
                    )
                ]
            )

        def with_retry(self, **kwargs):
            return self

    def with_structured_output(self, schema):
        return self._LLM()


@pytest.mark.asyncio
async def test_send_graph_produces_identical_transactions_across_concurrency_levels(
    monkeypatch,
):
    """FR-009 — the extracted transaction set is identical whether chunks run
    fully sequential (max_concurrency=1) or concurrent (max_concurrency=4)."""
    import app.features.ingestion.normalizer as normalizer_module

    # Four entries each > _MAX_CHUNK_CHARS so each is its own chunk.
    content_list = [{"type": "text", "text": f"chunk-marker-{i}" + "X" * 2000} for i in range(4)]

    async def _run(max_parallel: int) -> list[str]:
        monkeypatch.setattr(
            normalizer_module.settings.chat_model, "normalization_max_parallel_chunks", max_parallel
        )
        fake = _DeterministicByChunkChatModel()
        monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: fake)
        client = ChunkedLangGraphNormalizerClient()
        normalized, _ = await client.normalize(
            content_list,
            markdown="",
            known_categories=[],
            statement_id="stmt-1",
            ocr_result_id="ocr-1",
        )
        return sorted(t.merchant_raw for t in normalized.transactions)

    sequential = await _run(1)
    concurrent = await _run(4)

    expected = ["chunk-0", "chunk-1", "chunk-2", "chunk-3"]
    assert sequential == expected
    assert concurrent == expected


class _RetryExhaustingChatModel:
    """with_retry actually retries `stop_after_attempt` times; a failing chunk
    raises on every attempt so the retry budget is exhausted (FR-016)."""

    class _LLM:
        def __init__(self, good_result: ExtractedStatement, fail_when_call_gt: int):
            self._good = good_result
            self._fail_when_gt = fail_when_call_gt
            self.invoke_attempts = 0

        async def ainvoke(self, prompt, config=None):
            self.invoke_attempts += 1
            if self.invoke_attempts > self._fail_when_gt:
                raise RuntimeError("provider transient error")
            return self._good

        def with_retry(self, *, stop_after_attempt):
            outer = self

            class _Retried:
                async def ainvoke(self_inner, prompt, config=None):
                    exc: Exception | None = None
                    for _ in range(stop_after_attempt):
                        try:
                            return await outer.ainvoke(prompt, config=config)
                        except Exception as e:  # noqa: BLE001
                            exc = e
                    assert exc is not None
                    raise exc

            return _Retried()

    def __init__(self, good_result, fail_when_call_gt):
        self._llm = self._LLM(good_result, fail_when_call_gt)

    def with_structured_output(self, schema):
        return self._llm


@pytest.mark.asyncio
async def test_send_graph_one_chunk_exhausting_retries_fails_whole_invoke_with_no_partial(
    monkeypatch,
):
    """FR-016 — one chunk exhausting retries fails the entire ainvoke(); no
    partial result is returned even when another chunk already succeeded."""
    import app.features.ingestion.normalizer as normalizer_module

    monkeypatch.setattr(
        normalizer_module.settings.chat_model, "normalization_max_parallel_chunks", 1
    )

    good = ExtractedStatement(
        transactions=[
            ExtractedTransaction(
                transaction_date="2026-01-01",
                merchant_raw="succeeds",
                ai_description="The first chunk extracts cleanly.",
                category="other",
                amount=1.0,
                transaction_type="debit",
            )
        ]
    )
    # Two chunks, sequential (max_concurrency=1): call 1 succeeds, calls 2/3/4
    # (the second chunk's 3 retry attempts) all raise.
    fake = _RetryExhaustingChatModel(good_result=good, fail_when_call_gt=1)
    monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: fake)

    content_list = [
        {"type": "text", "text": "A" * 2000},
        {"type": "text", "text": "B" * 2000},
    ]
    client = ChunkedLangGraphNormalizerClient()

    with pytest.raises(Exception):  # noqa: B017
        await client.normalize(
            content_list,
            markdown="",
            known_categories=[],
            statement_id="stmt-1",
            ocr_result_id="ocr-1",
        )

    # 1 successful attempt + 3 exhausted attempts on the failing chunk = 4.
    assert fake._llm.invoke_attempts == 4


# ---------------------------------------------------------------------------
# US6 (FR-012/FR-013/FR-015) — business-context metadata at the extraction call site
# (no real model or Langfuse call; config asserted via a stub Runnable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_normalizer_client_accepts_and_ignores_statement_and_ocr_ids():
    """FR-012 — mock accepts the required kwargs and ignores them."""
    parsed, _ = await MockNormalizerClient().normalize(
        content_list=[{"type": "text", "text": "x"}],
        markdown="",
        known_categories=[],
        statement_id="stmt-1",
        ocr_result_id="ocr-1",
    )
    assert parsed.transactions


def test_normalizer_normalize_requires_statement_and_ocr_keyword_only_ids():
    """FR-012 — statement_id/ocr_result_id are required keyword-only params on
    every NormalizerClient implementer."""
    import inspect

    real = inspect.signature(ChunkedLangGraphNormalizerClient.normalize)
    mock = inspect.signature(MockNormalizerClient.normalize)
    for sig in (real, mock):
        assert sig.parameters["statement_id"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["ocr_result_id"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["statement_id"].default is inspect.Parameter.empty
        assert sig.parameters["ocr_result_id"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_extract_call_site_attaches_business_context_config(monkeypatch):
    """FR-012/FR-015 — each chunk's ainvoke() receives metadata + tags carrying
    statement_id, ocr_result_id, chunk_index, and prompt_version."""

    class _ConfigCapturingChatModel:
        class _LLM:
            def __init__(self):
                self.captured: list = []

            async def ainvoke(self, prompt, config=None):
                self.captured.append(config)
                return ExtractedStatement(
                    transactions=[
                        ExtractedTransaction(
                            transaction_date="2026-01-01",
                            merchant_raw="m",
                            ai_description="d",
                            category="other",
                            amount=1.0,
                            transaction_type="debit",
                        )
                    ]
                )

            def with_retry(self, **kwargs):
                return self

        def __init__(self):
            self._llm = self._LLM()

        def with_structured_output(self, schema):
            return self._llm

    fake = _ConfigCapturingChatModel()
    monkeypatch.setattr("app.core.llm.get_chat_model", lambda **kwargs: fake)

    content_list = [
        {"type": "text", "text": "A" * 2000},
        {"type": "text", "text": "B" * 2000},
    ]
    client = ChunkedLangGraphNormalizerClient()
    await client.normalize(
        content_list,
        markdown="",
        known_categories=[],
        statement_id="stmt-42",
        ocr_result_id="ocr-42",
    )

    assert len(fake._llm.captured) == 2
    indices = sorted(c["metadata"]["chunk_index"] for c in fake._llm.captured)
    assert indices == [0, 1]
    for config in fake._llm.captured:
        meta = config["metadata"]
        assert meta["statement_id"] == "stmt-42"
        assert meta["ocr_result_id"] == "ocr-42"
        assert meta["prompt_version"], "prompt_version is present and non-empty"
        assert f"ingestion.normalize.chunk:{meta['chunk_index']}" in config["tags"]


def test_prompt_version_is_stable_content_hash_of_template_source():
    """FR-013 — prompt_version is a deterministic hash of the committed template."""
    import hashlib
    from pathlib import Path

    import app.features.ingestion.normalizer.agents.chunked_langgraph.prompts as prompts_mod
    from app.features.ingestion.normalizer.agents.chunked_langgraph.prompts import (
        get_prompt_version,
    )

    v1 = get_prompt_version()
    v2 = get_prompt_version()
    assert v1 == v2, "stable across repeated calls"
    assert len(v1) == 8

    template_path = Path(prompts_mod.__file__).parent / "prompt_templates" / "normalization.jinja2"
    expected = hashlib.sha256(template_path.read_bytes()).hexdigest()[:8]
    assert v1 == expected, "derived from the committed template source"
    # A different template content would yield a different version.
    assert v1 != hashlib.sha256(b"different template content").hexdigest()[:8]
