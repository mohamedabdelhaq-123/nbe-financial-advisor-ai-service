"""Unit tests for ingestion service orchestration (US1/US2/US3)."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Select

from app.core.config import settings
from app.features.ingestion.mineru_client import ParsedDocument
from app.features.ingestion.service import process_statement

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


def _patch_storage(monkeypatch, s3):
    monkeypatch.setattr(
        "app.features.ingestion.service.get_storage_backend",
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
    monkeypatch.setattr("app.features.ingestion.service.get_mineru_client", lambda: client)


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
    assert result.prefix == f"{settings.storage_s3_ocr_bucket}/{STATEMENT_ID}/"

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
