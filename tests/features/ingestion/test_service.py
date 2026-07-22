"""Unit tests for ingestion service orchestration (US1/US2/US3)."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Select

from app.core.config import settings
from app.features.ingestion.mineru_client import ParsedDocument
from app.features.ingestion.service import normalize_statement, process_statement

STATEMENT_ID = str(uuid.uuid4())


class _FakeStatement:
    def __init__(self, seaweed_file_id: str):
        self.seaweed_file_id = seaweed_file_id


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeBackendSession:
    def __init__(self, row):
        self._row = row
        self.executed: list = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        return _FakeResult(self._row)


def _session_gen_for(row):
    session = _FakeBackendSession(row)

    async def _gen():
        yield session

    _gen.session = session
    return _gen


class _FakeOwnSession:
    def __init__(self):
        self.added: list = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True


def _own_session_gen():
    session = _FakeOwnSession()

    async def _gen():
        yield session

    _gen.session = session
    return _gen


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self):
        return self._data


class _FakeS3:
    def __init__(self, source_bytes: bytes = b"%PDF-fake", get_exc: Exception | None = None):
        self._source_bytes = source_bytes
        self._get_exc = get_exc
        self.get_calls: list = []
        self.put_calls: list = []

    async def get_object(self, Bucket, Key):
        self.get_calls.append((Bucket, Key))
        if self._get_exc:
            raise self._get_exc
        return {"Body": _FakeBody(self._source_bytes)}

    async def put_object(self, Bucket, Key, Body):
        self.put_calls.append((Bucket, Key, Body))


class _FakeStorageContext:
    def __init__(self, s3):
        self._s3 = s3

    async def __aenter__(self):
        return self._s3

    async def __aexit__(self, *exc):
        return False


def _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.process"):
    monkeypatch.setattr(
        f"{module}.get_storage_backend",
        lambda: _FakeStorageContext(s3),
    )


class _FakeMineruClient:
    def __init__(self, parsed: ParsedDocument | None = None, exc: Exception | None = None):
        self._parsed = parsed
        self._exc = exc
        self.calls: list = []

    async def parse_document(self, file_bytes, filename):
        self.calls.append((file_bytes, filename))
        if self._exc:
            raise self._exc
        return self._parsed


def _patch_mineru(monkeypatch, client):
    monkeypatch.setattr("app.features.ingestion.service.process.get_mineru_client", lambda: client)


# ---------------------------------------------------------------------------
# US1 — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_persists_markdown_and_content_list_with_tabular_structure(monkeypatch):
    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    s3 = _FakeS3()
    _patch_storage(monkeypatch, s3)

    parsed = ParsedDocument(
        markdown="# Statement",
        content_list=[
            {"type": "table", "rows": [["2026-01-01", "100.00"], ["2026-01-02", "50.00"]]}
        ],
        images={},
    )
    _patch_mineru(monkeypatch, _FakeMineruClient(parsed=parsed))

    result = await process_statement(
        session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
    )

    assert result.ocr_engine == "MinerU"
    assert result.prefix == f"{settings.storage.s3_ocr_bucket}/{STATEMENT_ID}/"
    assert result.confidence_score == 1.0

    put_keys = {key for _, key, _ in s3.put_calls}
    assert f"{STATEMENT_ID}/markdown.md" in put_keys
    assert f"{STATEMENT_ID}/content_list.json" in put_keys

    content_list_body = next(
        body for _, key, body in s3.put_calls if key == f"{STATEMENT_ID}/content_list.json"
    )
    saved = json.loads(content_list_body)
    assert saved[0]["rows"] == [["2026-01-01", "100.00"], ["2026-01-02", "50.00"]]


# ---------------------------------------------------------------------------
# US2 — durable persistence of all artifact kinds + zero backend writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_images_are_persisted_under_images_prefix(monkeypatch):
    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    s3 = _FakeS3()
    _patch_storage(monkeypatch, s3)

    parsed = ParsedDocument(
        markdown="# Statement",
        content_list=[],
        images={"fig1.jpg": b"jpeg-bytes", "fig2.png": b"png-bytes"},
    )
    _patch_mineru(monkeypatch, _FakeMineruClient(parsed=parsed))

    await process_statement(
        session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
    )

    put_keys = {key for _, key, _ in s3.put_calls}
    assert f"{STATEMENT_ID}/images/fig1.jpg" in put_keys
    assert f"{STATEMENT_ID}/images/fig2.png" in put_keys


@pytest.mark.asyncio
async def test_backend_session_issues_only_a_select(monkeypatch):
    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    _patch_storage(monkeypatch, _FakeS3())
    _patch_mineru(monkeypatch, _FakeMineruClient(parsed=ParsedDocument("md", [], {})))

    await process_statement(
        session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
    )

    executed = session_gen.session.executed
    assert len(executed) == 1
    assert isinstance(executed[0], Select)
    # The fake backend session exposes no write method at all (no add/commit) —
    # any write attempt against it would fail with AttributeError, so a clean
    # run through process_statement() structurally proves no write was issued.


@pytest.mark.asyncio
async def test_audit_row_recorded_after_successful_processing(monkeypatch):
    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    _patch_storage(monkeypatch, _FakeS3())
    _patch_mineru(monkeypatch, _FakeMineruClient(parsed=ParsedDocument("md", [], {})))

    result = await process_statement(
        session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
    )

    assert own_gen.session.committed is True
    assert len(own_gen.session.added) == 1
    audit_row = own_gen.session.added[0]
    assert audit_row.action == "ingestion.process"
    detail = json.loads(audit_row.detail_json)
    assert detail["statement_id"] == STATEMENT_ID
    assert detail["prefix"] == result.prefix


# ---------------------------------------------------------------------------
# US3 — explicit failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_statement_returns_404_before_any_external_call(monkeypatch):
    session_gen = _session_gen_for(None)
    own_gen = _own_session_gen()

    s3 = _FakeS3()
    _patch_storage(monkeypatch, s3)
    mineru = _FakeMineruClient(parsed=ParsedDocument("md", [], {}))
    _patch_mineru(monkeypatch, mineru)

    with pytest.raises(HTTPException) as exc_info:
        await process_statement(
            session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
        )

    assert exc_info.value.status_code == 404
    assert s3.get_calls == []
    assert s3.put_calls == []
    assert mineru.calls == []


@pytest.mark.asyncio
async def test_malformed_seaweed_file_id_returns_502_source_retrieval_failure(monkeypatch):
    row = _FakeStatement(seaweed_file_id="no-slash-in-this-value")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    mineru = _FakeMineruClient(parsed=ParsedDocument("md", [], {}))
    _patch_mineru(monkeypatch, mineru)

    with pytest.raises(HTTPException) as exc_info:
        await process_statement(
            session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
        )

    assert exc_info.value.status_code == 502
    assert "source document" in exc_info.value.detail
    assert mineru.calls == []


@pytest.mark.asyncio
async def test_source_fetch_failure_returns_502_source_retrieval_failure(monkeypatch):
    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    s3 = _FakeS3(get_exc=RuntimeError("object not found"))
    _patch_storage(monkeypatch, s3)
    mineru = _FakeMineruClient(parsed=ParsedDocument("md", [], {}))
    _patch_mineru(monkeypatch, mineru)

    with pytest.raises(HTTPException) as exc_info:
        await process_statement(
            session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
        )

    assert exc_info.value.status_code == 502
    assert "source document" in exc_info.value.detail
    assert mineru.calls == []


@pytest.mark.asyncio
async def test_mineru_failure_returns_502_processing_engine_failure(monkeypatch):
    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    _patch_storage(monkeypatch, _FakeS3())
    _patch_mineru(monkeypatch, _FakeMineruClient(exc=RuntimeError("connection refused")))

    with pytest.raises(HTTPException) as exc_info:
        await process_statement(
            session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
        )

    assert exc_info.value.status_code == 502
    assert "processing engine" in exc_info.value.detail


@pytest.mark.asyncio
async def test_offline_mode_setting_alone_routes_through_mock_mineru(monkeypatch):
    import app.features.ingestion.mineru_client as mineru_client_module

    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    s3 = _FakeS3()
    _patch_storage(monkeypatch, s3)
    monkeypatch.setattr(mineru_client_module.settings.mineru, "use_mock", True)

    await process_statement(
        session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
    )

    markdown_body = next(
        body for _, key, body in s3.put_calls if key == f"{STATEMENT_ID}/markdown.md"
    )
    content_list_body = next(
        body for _, key, body in s3.put_calls if key == f"{STATEMENT_ID}/content_list.json"
    )
    assert markdown_body
    content_list = json.loads(content_list_body)
    assert any(entry["type"] == "text" for entry in content_list)
    assert any(entry["type"] == "table" for entry in content_list)


@pytest.mark.asyncio
async def test_empty_content_still_returns_a_successful_result(monkeypatch):
    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen()

    s3 = _FakeS3()
    _patch_storage(monkeypatch, s3)
    _patch_mineru(
        monkeypatch,
        _FakeMineruClient(parsed=ParsedDocument(markdown="", content_list=[], images={})),
    )

    result = await process_statement(
        session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
    )

    assert result.ocr_engine == "MinerU"
    assert result.confidence_score == 1.0
    put_keys = {key for _, key, _ in s3.put_calls}
    assert f"{STATEMENT_ID}/markdown.md" in put_keys
    assert f"{STATEMENT_ID}/content_list.json" in put_keys


# ---------------------------------------------------------------------------
# US2 — audit row against a real (Testcontainers) own DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_row_persisted_in_real_own_db(monkeypatch, own_pg):
    from sqlalchemy import select as sa_select

    from app.features.audit.models import AiAuditLog

    def _own_session_gen_from_pg():
        async def _gen():
            async with own_pg() as session:
                yield session

        return _gen

    row = _FakeStatement(seaweed_file_id="pfm-statements-raw/u1/s1/original.pdf")
    session_gen = _session_gen_for(row)
    own_gen = _own_session_gen_from_pg()

    _patch_storage(monkeypatch, _FakeS3())
    _patch_mineru(monkeypatch, _FakeMineruClient(parsed=ParsedDocument("md", [], {})))

    result = await process_statement(
        session_gen=session_gen, own_session_gen=own_gen, statement_id=STATEMENT_ID
    )

    async with own_pg() as session:
        rows = (
            (
                await session.execute(
                    sa_select(AiAuditLog).where(AiAuditLog.action == "ingestion.process")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)
    assert detail["statement_id"] == STATEMENT_ID
    assert detail["prefix"] == result.prefix


# ---------------------------------------------------------------------------
# normalize_statement() — US1/US2/US3/US4
# ---------------------------------------------------------------------------


OCR_RESULT_ID = str(uuid.uuid4())
NORM_STATEMENT_ID = uuid.uuid4()
NORM_USER_ID = uuid.uuid4()


class _FakeOcrResult:
    def __init__(self, statement_id):
        self.statement_id = statement_id


class _FakeNormResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def all(self):
        return self._value


class _FakeNormBackendSession:
    """Queues canned responses for the ocr_result/user_id/duplicate-check
    lookups, but delegates category queries (known_categories/resolve_category)
    to a real Postgres session — those need the actual seeded `categories`
    mock table (tests/conftest.py's `own_db_url`), not a scripted response.
    """

    def __init__(self, responses: list, real_session=None):
        # `responses` is the SAME list instance across every session_gen()
        # invocation within one test (normalize_statement calls session_gen()
        # multiple times) — popping must drain it in true call order, not
        # reset on each invocation, so this must NOT be a copy.
        self._responses = responses
        self.executed: list = []
        self._real_session = real_session

    async def execute(self, stmt):
        self.executed.append(stmt)
        if "categories" in str(stmt).lower():
            return await self._real_session.execute(stmt)
        return self._responses.pop(0)


def _normalize_session_gen(ocr_result_row, user_id=None, dup_rows=(), own_pg=None):
    responses = [_FakeNormResult(ocr_result_row)]
    if ocr_result_row is not None:
        responses.append(_FakeNormResult(user_id))
        responses.append(_FakeNormResult(list(dup_rows)))

    async def _gen():
        async with own_pg() as real_session:
            yield _FakeNormBackendSession(responses, real_session=real_session)

    return _gen


def _own_session_gen_from_pg(own_pg):
    async def _gen():
        async with own_pg() as session:
            yield session

    return _gen


class _FakeOcrObjectBody:
    def __init__(self, data: bytes):
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self):
        return self._data


class _FakeOcrStorage:
    def __init__(self, objects: dict[str, bytes], get_exc: Exception | None = None):
        self._objects = objects
        self._get_exc = get_exc
        self.get_calls: list = []
        self.put_calls: list = []

    async def get_object(self, Bucket, Key):
        self.get_calls.append((Bucket, Key))
        if self._get_exc:
            raise self._get_exc
        return {"Body": _FakeOcrObjectBody(self._objects[Key])}

    async def put_object(self, Bucket, Key, Body):
        self.put_calls.append((Bucket, Key, Body))


def _ocr_objects(
    statement_id, markdown: str = "# Statement\nsome text", content_list: list | None = None
):
    prefix = f"{statement_id}/"
    return {
        f"{prefix}markdown.md": markdown.encode("utf-8"),
        f"{prefix}content_list.json": json.dumps(
            content_list if content_list is not None else [{"type": "text", "text": "line"}]
        ).encode("utf-8"),
    }


class _FakeNormalizerClient:
    def __init__(self, result=None, exc: Exception | None = None):
        self._result = result
        self._exc = exc

    async def normalize(self, content_list, markdown, known_categories):
        if self._exc:
            raise self._exc
        return self._result


@pytest.mark.asyncio
async def test_normalize_happy_path_returns_categorized_transactions(
    monkeypatch,
    own_pg,
):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    assert result.model_used
    assert result.normalized_json["transactions"], "expected at least one transaction"
    txn = result.normalized_json["transactions"][0]
    assert txn["category"] in {
        "housing",
        "food",
        "transport",
        "savings",
        "lifestyle",
        "other",
        "salary",
        "transfers_in",
        "other_income",
    }
    assert txn["duplicate_of"] is None

    put_keys = {key for _, key, _ in s3.put_calls}
    assert f"{NORM_STATEMENT_ID}/normalized.json" in put_keys


@pytest.mark.asyncio
async def test_normalize_unknown_ocr_result_returns_404(monkeypatch, own_pg):
    session_gen = _normalize_session_gen(None, own_pg=own_pg)
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage({})
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    with pytest.raises(HTTPException) as exc_info:
        await normalize_statement(
            session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
        )

    assert exc_info.value.status_code == 404
    assert s3.get_calls == []


@pytest.mark.asyncio
async def test_normalize_missing_ocr_artifacts_returns_502(monkeypatch, own_pg):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage({}, get_exc=RuntimeError("no such key"))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    with pytest.raises(HTTPException) as exc_info:
        await normalize_statement(
            session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
        )

    assert exc_info.value.status_code == 502
    assert "OCR content" in exc_info.value.detail


@pytest.mark.asyncio
async def test_normalize_engine_failure_returns_502(monkeypatch, own_pg):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    monkeypatch.setattr(
        "app.features.ingestion.service.normalize.get_normalizer_client",
        lambda: _FakeNormalizerClient(exc=RuntimeError("model unavailable")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await normalize_statement(
            session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
        )

    assert exc_info.value.status_code == 502
    assert "normalization engine" in exc_info.value.detail
    assert s3.put_calls == []


@pytest.mark.asyncio
async def test_normalize_empty_content_returns_success_with_no_transactions(
    monkeypatch,
    own_pg,
):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID, markdown="", content_list=[]))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    assert result.normalized_json["transactions"] == []


# ---------------------------------------------------------------------------
# normalize_statement() — US2: duplicate flagging (full flow)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalize_flags_duplicate_when_backend_query_matches(
    monkeypatch,
    own_pg,
):
    existing_id = uuid.uuid4()
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[(existing_id, "2026-01-01")],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    async def _fake_find_duplicate(session, user_id, transaction_date, amount):
        return str(existing_id)

    monkeypatch.setattr(
        "app.features.ingestion.service.normalize.find_duplicate", _fake_find_duplicate
    )

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    txn = result.normalized_json["transactions"][0]
    assert txn["duplicate_of"] == str(existing_id)


# ---------------------------------------------------------------------------
# normalize_statement() — US3: unmatched category falls back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalize_unmatched_category_falls_back_to_other(
    monkeypatch,
    own_pg,
):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    monkeypatch.setattr(
        "app.features.ingestion.service.normalize.get_normalizer_client",
        lambda: _FakeNormalizerClient(
            result=(
                {
                    "bank_name": "Test Bank",
                    "account_hint": "****1234",
                    "transactions": [
                        {
                            "transaction_date": "2026-05-01",
                            "merchant_raw": "Some Merchant",
                            "category": "spelunking-equipment",
                            "amount": 42.0,
                            "transaction_type": "debit",
                        }
                    ],
                },
                "test-model",
            )
        ),
    )

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    assert result.normalized_json["transactions"][0]["category"] == "other"


@pytest.mark.asyncio
async def test_normalize_transaction_extra_fields_are_passed_through(
    monkeypatch,
    own_pg,
):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    monkeypatch.setattr(
        "app.features.ingestion.service.normalize.get_normalizer_client",
        lambda: _FakeNormalizerClient(
            result=(
                {
                    "bank_name": "Test Bank",
                    "account_hint": "****1234",
                    "transactions": [
                        {
                            "transaction_date": "2026-05-01",
                            "merchant_raw": "Some Merchant",
                            "category": "other",
                            "amount": 42.0,
                            "transaction_type": "debit",
                            "extra_fields": [{"key": "reference_number", "value": "REF123"}],
                        }
                    ],
                },
                "test-model",
            )
        ),
    )

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    assert result.normalized_json["transactions"][0]["extra_fields"] == [
        {"key": "reference_number", "value": "REF123"}
    ]


@pytest.mark.asyncio
async def test_normalize_transaction_without_extra_fields_omits_the_key(
    monkeypatch,
    own_pg,
):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    assert "extra_fields" not in result.normalized_json["transactions"][0]


@pytest.mark.asyncio
async def test_normalize_skips_transactions_with_malformed_or_missing_date_or_amount(
    monkeypatch,
    own_pg,
):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    monkeypatch.setattr(
        "app.features.ingestion.service.normalize.get_normalizer_client",
        lambda: _FakeNormalizerClient(
            result=(
                {
                    "bank_name": "Test Bank",
                    "account_hint": "****1234",
                    "transactions": [
                        {
                            "transaction_date": "not-a-date",
                            "merchant_raw": "Malformed Date",
                            "category": "other",
                            "amount": 10.0,
                            "transaction_type": "debit",
                        },
                        {
                            "merchant_raw": "Missing Date",
                            "category": "other",
                            "amount": 10.0,
                            "transaction_type": "debit",
                        },
                        {
                            "transaction_date": "2026-05-01",
                            "merchant_raw": "Malformed Amount",
                            "category": "other",
                            "amount": "not-a-number",
                            "transaction_type": "debit",
                        },
                        {
                            "transaction_date": "2026-05-01",
                            "merchant_raw": "Missing Amount",
                            "category": "other",
                            "transaction_type": "debit",
                        },
                        {
                            "transaction_date": "2026-05-01",
                            "merchant_raw": "Valid Transaction",
                            "category": "other",
                            "amount": 42.0,
                            "transaction_type": "debit",
                        },
                    ],
                },
                "test-model",
            )
        ),
    )

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    assert len(result.normalized_json["transactions"]) == 1
    assert result.normalized_json["transactions"][0]["merchant_raw"] == "Valid Transaction"


# ---------------------------------------------------------------------------
# normalize_statement() — US4: persisted object matches returned result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalize_persisted_object_matches_returned_result(
    monkeypatch,
    own_pg,
):
    session_gen = _normalize_session_gen(
        _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
        user_id=NORM_USER_ID,
        dup_rows=[],
        own_pg=own_pg,
    )
    own_gen = _own_session_gen_from_pg(own_pg)

    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")

    result = await normalize_statement(
        session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
    )

    persisted_body = next(
        body for _, key, body in s3.put_calls if key == f"{NORM_STATEMENT_ID}/normalized.json"
    )
    assert json.loads(persisted_body) == result.normalized_json


@pytest.mark.asyncio
async def test_normalize_reprocessing_overwrites_same_key(monkeypatch, own_pg):
    s3 = _FakeOcrStorage(_ocr_objects(NORM_STATEMENT_ID))
    _patch_storage(monkeypatch, s3, module="app.features.ingestion.service.normalize")
    own_gen = _own_session_gen_from_pg(own_pg)

    for _ in range(2):
        session_gen = _normalize_session_gen(
            _FakeOcrResult(statement_id=NORM_STATEMENT_ID),
            user_id=NORM_USER_ID,
            dup_rows=[],
            own_pg=own_pg,
        )
        await normalize_statement(
            session_gen=session_gen, own_session_gen=own_gen, ocr_result_id=OCR_RESULT_ID
        )

    normalize_put_keys = [
        key for _, key, _ in s3.put_calls if key == f"{NORM_STATEMENT_ID}/normalized.json"
    ]
    assert len(normalize_put_keys) == 2
