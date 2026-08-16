"""Unit tests: asynchronous ingestion job surface — submission, dedup, and delegation.

Deliberately queue-free. Status derivation itself (`derive_state()`) is generic and lives
in `app.core.tasks`, tested at `tests/core/test_tasks.py`; this file covers what is
actually ingestion-specific: target validation, deduplication, and the job functions'
delegation to the unchanged blocking pipeline.
"""

import uuid

import pytest
from fastapi import HTTPException
from saq.job import Status

from app.core.tasks.schemas import epoch_ms_to_datetime
from app.features.ingestion.service import jobs as service

STATEMENT_ID = "3f8a1c2e-0000-4000-8000-000000000000"
OCR_RESULT_ID = "4a9b2d3f-0000-4000-8000-000000000000"

PROCESS_RESULT = {
    "prefix": "pfm-statements-ocr/3f8a1c2e/",
    "ocr_engine": "MinerU",
    "confidence_score": 1.0,
}


class _FakeJob:
    """Stands in for saq.Job — only the fields the status surface reads."""

    def __init__(self, key="job-1", function="ingestion.process", status=Status.QUEUED, **kw):
        self.key = key
        self.function = function
        self.status = status
        self.kwargs = kw.pop("kwargs", {"statement_id": STATEMENT_ID})
        self.result = kw.pop("result", None)
        self.error = kw.pop("error", None)
        self.queued = kw.pop("queued", 1_764_000_000_000)
        self.started = kw.pop("started", 0)
        self.completed = kw.pop("completed", 0)


class _FakeQueue:
    """Stands in for saq.Queue — `job()`, `enqueue()`, and the `iter_jobs()` scan the
    submission path uses to recognise a target that already has work in flight."""

    def __init__(self, jobs=None, enqueue_result=None):
        self._jobs = jobs or {}
        self.enqueued = []
        self._enqueue_result = enqueue_result

    async def job(self, key):
        return self._jobs.get(key)

    async def iter_jobs(self, statuses=None, batch_size=100):
        for job in list(self._jobs.values()):
            if statuses is None or job.status in statuses:
                yield job

    async def enqueue(self, function, **kwargs):
        self.enqueued.append((function, kwargs))
        job = self._enqueue_result or _FakeJob(
            key=f"job-{len(self.enqueued)}",
            function=function,
            kwargs={k: v for k, v in kwargs.items() if k in ("statement_id", "ocr_result_id")},
        )
        self._jobs[job.key] = job
        return job


@pytest.fixture
def fake_queue(monkeypatch):
    queue = _FakeQueue()
    monkeypatch.setattr(service, "get_queue", lambda: queue)
    return queue


def _own_session_gen(session):
    async def _gen():
        yield session

    return _gen


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _FakeSession:
    """Minimal own-DB session: one canned row, and recording of commits."""

    def __init__(self, row=None):
        self.row = row
        self.commits = 0
        self.executed = []

    async def execute(self, stmt, params=None):
        self.executed.append(stmt)
        return _FakeResult(self.row)

    async def commit(self):
        self.commits += 1


def _backend_session_gen(exists: bool):
    class _Session:
        async def execute(self, stmt):
            return _FakeResult(uuid.uuid4() if exists else None)

    async def _gen():
        yield _Session()

    return _gen


# --- submission -------------------------------------------------------------


async def test_submit_extraction_enqueues_and_acknowledges_as_queued(fake_queue):
    session = _FakeSession(row=None)
    response = await service.submit_extraction_job(
        _backend_session_gen(True),
        _own_session_gen(session),
        STATEMENT_ID,
    )

    assert response.state == "queued"
    assert response.step == "process"
    assert response.job_id
    assert session.commits == 1

    function, kwargs = fake_queue.enqueued[0]
    assert function == "ingestion.process"
    assert kwargs["statement_id"] == STATEMENT_ID
    # The three SAQ defaults that would silently break this feature.
    assert kwargs["timeout"] == 0
    assert kwargs["ttl"] == 30 * 24 * 60 * 60
    assert kwargs["heartbeat"] > 0


async def test_submit_normalization_enqueues_the_normalize_function(fake_queue):
    session = _FakeSession(row=None)
    response = await service.submit_normalization_job(
        _backend_session_gen(True),
        _own_session_gen(session),
        OCR_RESULT_ID,
    )

    assert response.step == "normalize"
    function, kwargs = fake_queue.enqueued[0]
    assert function == "ingestion.normalize"
    assert kwargs["ocr_result_id"] == OCR_RESULT_ID


async def test_unknown_statement_is_rejected_without_creating_a_job(fake_queue):
    session = _FakeSession(row=None)
    with pytest.raises(HTTPException) as exc:
        await service.submit_extraction_job(
            _backend_session_gen(False),
            _own_session_gen(session),
            STATEMENT_ID,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "statement not found"
    assert fake_queue.enqueued == []
    assert session.commits == 0


async def test_unknown_ocr_result_is_rejected_without_creating_a_job(fake_queue):
    session = _FakeSession(row=None)
    with pytest.raises(HTTPException) as exc:
        await service.submit_normalization_job(
            _backend_session_gen(False),
            _own_session_gen(session),
            OCR_RESULT_ID,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "ocr result not found"
    assert fake_queue.enqueued == []


# --- deduplication --------------------------------------------------------
#
# The in-flight lookup is a scan of the queue's own non-terminal jobs, so these seed the
# fake queue rather than any table of ours.


async def test_repeat_submission_returns_the_in_flight_job(monkeypatch):
    live = _FakeJob(key="job-live", status=Status.ACTIVE)
    queue = _FakeQueue(jobs={"job-live": live})
    monkeypatch.setattr(service, "get_queue", lambda: queue)

    response = await service.submit_extraction_job(
        _backend_session_gen(True),
        _own_session_gen(_FakeSession()),
        STATEMENT_ID,
    )

    assert response.job_id == "job-live"
    assert response.state == "running"
    assert queue.enqueued == [], "an in-flight target must not start a second execution"


async def test_submission_takes_an_advisory_lock_before_scanning(monkeypatch):
    """The lock is what makes the scan safe against a simultaneous duplicate submit."""
    queue = _FakeQueue()
    monkeypatch.setattr(service, "get_queue", lambda: queue)
    session = _FakeSession()

    await service.submit_extraction_job(
        _backend_session_gen(True),
        _own_session_gen(session),
        STATEMENT_ID,
    )

    statements = [str(s) for s in session.executed]
    assert any("pg_advisory_xact_lock" in s for s in statements)
    assert session.commits == 1, "the lock must be released by committing the transaction"


async def test_resubmission_after_terminal_starts_a_new_job(monkeypatch):
    """FR-011: the previous job's record still exists — a retry must not collide with it."""
    finished = _FakeJob(key="job-old", status=Status.COMPLETE, result={"ok": True, "result": {}})
    queue = _FakeQueue(jobs={"job-old": finished})
    monkeypatch.setattr(service, "get_queue", lambda: queue)

    response = await service.submit_extraction_job(
        _backend_session_gen(True),
        _own_session_gen(_FakeSession()),
        STATEMENT_ID,
    )

    assert response.job_id != "job-old"
    assert len(queue.enqueued) == 1


async def test_in_flight_job_for_a_different_target_does_not_block_submission(monkeypatch):
    """The scan matches on the target, not merely on the step."""
    other = _FakeJob(
        key="job-other",
        status=Status.ACTIVE,
        kwargs={"statement_id": "9999c2e0-0000-4000-8000-000000000000"},
    )
    queue = _FakeQueue(jobs={"job-other": other})
    monkeypatch.setattr(service, "get_queue", lambda: queue)

    response = await service.submit_extraction_job(
        _backend_session_gen(True),
        _own_session_gen(_FakeSession()),
        STATEMENT_ID,
    )

    assert response.job_id != "job-other"
    assert len(queue.enqueued) == 1


async def test_submission_sets_a_group_key_so_duplicates_can_never_run_concurrently(
    monkeypatch,
):
    queue = _FakeQueue()
    monkeypatch.setattr(service, "get_queue", lambda: queue)

    await service.submit_extraction_job(
        _backend_session_gen(True),
        _own_session_gen(_FakeSession()),
        STATEMENT_ID,
    )

    _, kwargs = queue.enqueued[0]
    assert kwargs["group_key"] == f"process:{STATEMENT_ID}"


# --- delegation to the blocking pipeline -----------------------------------


async def test_process_job_delegates_to_the_untouched_blocking_service(monkeypatch):
    """FR-015 / SC-004 hold by construction: the async path runs the same function.

    The audit row, the result shape, and the diagnostic strings all originate inside
    `process_statement()`. Asserting the delegation — same function, same session
    generators — is what proves the async path cannot drift from the blocking one.
    """
    from app.backend_db import get_backend_session
    from app.core.db import get_own_session
    from app.features.ingestion import tasks

    captured = {}

    class _Result:
        def model_dump(self, mode=None):
            return PROCESS_RESULT

    async def _spy(session_gen, own_session_gen, statement_id):
        captured.update(
            session_gen=session_gen, own_session_gen=own_session_gen, statement_id=statement_id
        )
        return _Result()

    monkeypatch.setattr(tasks, "process_statement", _spy)

    envelope = await tasks.process_job({}, statement_id=STATEMENT_ID)

    assert envelope == {"ok": True, "result": PROCESS_RESULT}
    assert captured["session_gen"] is get_backend_session
    assert captured["own_session_gen"] is get_own_session
    assert captured["statement_id"] == STATEMENT_ID


async def test_normalize_job_delegates_to_the_untouched_blocking_service(monkeypatch):
    from app.features.ingestion import tasks

    captured = {}

    class _Result:
        def model_dump(self, mode=None):
            return {"normalized_json": {"transactions": []}, "model_used": "gpt-4o-mini"}

    async def _spy(session_gen, own_session_gen, ocr_result_id):
        captured["ocr_result_id"] = ocr_result_id
        return _Result()

    monkeypatch.setattr(tasks, "normalize_statement", _spy)

    envelope = await tasks.normalize_job({}, ocr_result_id=OCR_RESULT_ID)

    assert envelope["ok"] is True
    assert envelope["result"]["model_used"] == "gpt-4o-mini"
    assert captured["ocr_result_id"] == OCR_RESULT_ID


async def test_job_envelope_carries_http_detail_verbatim(monkeypatch):
    from app.features.ingestion import tasks

    async def _boom(session_gen, own_session_gen, statement_id):
        raise HTTPException(status_code=502, detail="failed to retrieve source document: nope")

    monkeypatch.setattr(tasks, "process_statement", _boom)

    envelope = await tasks.process_job({}, statement_id=STATEMENT_ID)

    assert envelope == {"ok": False, "error": "failed to retrieve source document: nope"}


async def test_unexpected_exception_propagates_rather_than_being_swallowed(monkeypatch):
    """Operators keep the trace; SAQ records the job as failed."""
    from app.features.ingestion import tasks

    async def _boom(session_gen, own_session_gen, statement_id):
        raise ValueError("kaboom")

    monkeypatch.setattr(tasks, "process_statement", _boom)

    with pytest.raises(ValueError):
        await tasks.process_job({}, statement_id=STATEMENT_ID)


# --- routes -----------------------------------------------------------------


def test_submit_process_job_401_without_token(client):
    resp = client.post("/internal/ingestion/jobs/process", json={"statement_id": STATEMENT_ID})
    assert resp.status_code == 401


def test_submit_normalize_job_401_without_token(client):
    resp = client.post("/internal/ingestion/jobs/normalize", json={"ocr_result_id": OCR_RESULT_ID})
    assert resp.status_code == 401


def test_submit_process_job_202_with_token(client, auth_headers, monkeypatch):
    from app.features.ingestion.schemas import JobSubmissionResponse

    async def _mock_submit(session_gen, own_session_gen, statement_id):
        return JobSubmissionResponse(
            job_id="job-1",
            step="process",
            state="queued",
            submitted_at=epoch_ms_to_datetime(1_764_000_000_000),
        )

    monkeypatch.setattr("app.features.ingestion.router.submit_extraction_job", _mock_submit)

    resp = client.post(
        "/internal/ingestion/jobs/process",
        json={"statement_id": STATEMENT_ID},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    assert resp.json()["job_id"] == "job-1"
    assert resp.json()["state"] == "queued"
