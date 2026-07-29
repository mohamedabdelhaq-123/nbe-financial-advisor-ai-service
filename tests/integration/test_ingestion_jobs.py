"""Integration tests: the ingestion job surface against real SAQ on real Postgres.

SAQ's Postgres backend has no offline mode, so everything that is genuinely a storage
guarantee — its self-migration, deduplication against a live job, retry once terminal,
retention, and the sweep that reclaims an orphaned job — has to be proven here rather
than against a fake. The pipeline itself is stubbed: no test issues a real model, MinerU,
or storage call (Constitution I).
"""

import asyncio
import uuid

import pytest
from saq.job import Status
from saq.utils import now

from app.core.tasks import queue as queue_module
from app.core.tasks import worker as worker_module
from app.core.tasks.queue import SWEPT_ERROR_MESSAGE
from app.core.tasks.schemas import TaskState
from app.core.tasks.service import TaskNotFoundError, get_task_status
from app.features.ingestion.service import jobs as service
from app.features.ingestion.service.jobs import JOB_TTL
from app.features.ingestion.tasks import JOB_FUNCTIONS

STATEMENT_ID = "3f8a1c2e-0000-4000-8000-000000000000"


def _psycopg_url(async_url: str) -> str:
    """Testcontainers hands us a SQLAlchemy asyncpg URL; SAQ speaks psycopg."""
    return async_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def job_queue(own_db_url, monkeypatch):
    queue = queue_module.build_queue(_psycopg_url(own_db_url))
    await queue.connect()
    monkeypatch.setattr(service, "get_queue", lambda: queue)
    queue_module.set_queue(queue)
    yield queue
    queue_module.set_queue(None)
    await queue.disconnect()


@pytest.fixture
def backend_session_gen():
    """Stands in for the read-only backend DB: the target always exists."""

    class _Result:
        def scalar_one_or_none(self):
            return uuid.uuid4()

    class _Session:
        async def execute(self, stmt):
            return _Result()

    async def _gen():
        yield _Session()

    return _gen


@pytest.fixture
def own_session_gen(own_pg):
    async def _gen():
        async with own_pg() as session:
            yield session

    return _gen


@pytest.fixture(autouse=True)
async def _clean_state(job_queue, own_pg):
    """Each test starts with no jobs.

    The Testcontainers Postgres is session-scoped, so without this a test asserting
    "exactly one job was enqueued" would count its predecessors'.
    """
    from sqlalchemy import text

    async with own_pg() as session:
        await session.execute(text("DELETE FROM saq_jobs"))
        await session.commit()
    yield


_TERMINAL = {TaskState.SUCCEEDED.value, TaskState.FAILED.value}


async def _drain(job_queue, job_key, timeout=10.0):
    """Run a worker until `job_key` is terminal, then stop it and report the status."""
    worker = worker_module.build_worker(job_queue, functions=JOB_FUNCTIONS)
    task = asyncio.create_task(worker.start())
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
            status = await get_task_status(job_key)
            if status.state in _TERMINAL:
                return status
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    raise AssertionError(f"job {job_key} did not reach a terminal state within {timeout}s")


async def test_queue_connect_creates_its_own_tables(job_queue, own_pg):
    """SAQ self-migrates; no Alembic migration covers saq_* and none should."""
    from sqlalchemy import text

    async with own_pg() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_name LIKE 'saq_%'"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert {"saq_jobs", "saq_stats", "saq_versions"} <= set(rows)


async def test_submission_is_readable_immediately_and_carries_the_overridden_ttl(
    job_queue, backend_session_gen, own_session_gen
):
    """SC-001 / the "checks immediately after submitting" edge case, plus the FR-016 setting."""
    submitted = await service.submit_extraction_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )

    status = await get_task_status(submitted.job_id)
    assert status.state == TaskState.QUEUED.value
    assert status.function == "ingestion.process"

    job = await job_queue.job(submitted.job_id)
    assert job.ttl == JOB_TTL, "a default ttl would delete results 10 minutes after completion"
    assert job.timeout == 0, "a default timeout would kill every real extraction at 10s"


async def test_repeat_submission_returns_the_same_job_and_enqueues_once(
    job_queue, backend_session_gen, own_session_gen, own_pg
):
    """FR-010 / SC-006 — exactly one execution for a target submitted twice."""
    from sqlalchemy import text

    first = await service.submit_extraction_job(backend_session_gen, own_session_gen, STATEMENT_ID)
    second = await service.submit_extraction_job(backend_session_gen, own_session_gen, STATEMENT_ID)

    assert first.job_id == second.job_id
    assert first.submitted_at == second.submitted_at

    async with own_pg() as session:
        jobs = (await session.execute(text("SELECT count(*) FROM saq_jobs"))).scalar_one()

    assert jobs == 1, "a second job was enqueued for a target already in flight"


async def test_simultaneous_submissions_produce_one_job(
    job_queue, backend_session_gen, own_session_gen, own_pg
):
    """The advisory lock's reason for existing.

    Without it, both submissions would scan for an in-flight job, both find nothing, and
    both enqueue — which is exactly the duplicate execution SC-006 forbids. There is no
    unique constraint standing behind this any more, so it has to be tested.
    """
    from sqlalchemy import text

    first, second = await asyncio.gather(
        service.submit_extraction_job(backend_session_gen, own_session_gen, STATEMENT_ID),
        service.submit_extraction_job(backend_session_gen, own_session_gen, STATEMENT_ID),
    )

    assert first.job_id == second.job_id

    async with own_pg() as session:
        jobs = (await session.execute(text("SELECT count(*) FROM saq_jobs"))).scalar_one()

    assert jobs == 1, "concurrent submissions raced past the advisory lock"


async def test_the_two_steps_deduplicate_independently(
    job_queue, backend_session_gen, own_session_gen
):
    """An in-flight extraction must not suppress a normalization, or vice versa."""
    extraction = await service.submit_extraction_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )
    normalization = await service.submit_normalization_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )

    assert extraction.job_id != normalization.job_id
    assert extraction.step == "process"
    assert normalization.step == "normalize"


async def test_retry_after_terminal_starts_a_new_job_while_the_old_record_remains(
    job_queue, backend_session_gen, own_session_gen, own_pg
):
    """FR-011 + FR-008 — the case naive key-based deduplication gets wrong.

    The finished job's record is still present (30-day retention), so a deterministic
    job key would collide with it here instead of starting a retry. The in-flight scan
    ignores it because it is terminal.
    """
    first = await service.submit_extraction_job(backend_session_gen, own_session_gen, STATEMENT_ID)
    job = await job_queue.job(first.job_id)
    job.status = Status.COMPLETE
    job.result = {"ok": True, "result": {"prefix": "p/", "ocr_engine": "MinerU"}}
    await job_queue.finish(job, Status.COMPLETE, result=job.result)

    second = await service.submit_extraction_job(backend_session_gen, own_session_gen, STATEMENT_ID)

    assert second.job_id != first.job_id

    # The old record is untouched and still readable with its original outcome.
    old = await get_task_status(first.job_id)
    assert old.state == TaskState.SUCCEEDED.value

    # ...and the new one is live, so a third submission now dedupes against it.
    third = await service.submit_extraction_job(backend_session_gen, own_session_gen, STATEMENT_ID)
    assert third.job_id == second.job_id


async def test_worker_executes_a_job_and_the_result_is_collectable(
    job_queue, backend_session_gen, own_session_gen, monkeypatch
):
    """The end-to-end path: submit → worker executes → terminal state carries the result."""
    from app.features.ingestion import tasks

    expected = {"prefix": "pfm-statements-ocr/x/", "ocr_engine": "MinerU", "confidence_score": 1.0}

    class _Result:
        def model_dump(self, mode=None):
            return expected

    async def _fake_process(session_gen, own_session_gen, statement_id):
        return _Result()

    monkeypatch.setattr(tasks, "process_statement", _fake_process)

    submitted = await service.submit_extraction_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )

    worker = worker_module.build_worker(job_queue, functions=JOB_FUNCTIONS)
    task = asyncio.create_task(worker.start())
    try:
        for _ in range(100):
            await asyncio.sleep(0.1)
            status = await get_task_status(submitted.job_id)
            if status.state in (TaskState.SUCCEEDED.value, TaskState.FAILED.value):
                break
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert status.state == TaskState.SUCCEEDED.value
    assert status.result == expected
    assert status.started_at is not None
    assert status.finished_at is not None

    # Read again — terminal content must not change (FR-008).
    again = await get_task_status(submitted.job_id)
    assert again.model_dump() == status.model_dump()


async def test_pipeline_failure_preserves_the_blocking_endpoints_diagnostic(
    job_queue, backend_session_gen, own_session_gen, monkeypatch
):
    """FR-007."""
    from fastapi import HTTPException

    from app.features.ingestion import tasks

    detail = "document processing engine failed: connection refused"

    async def _boom(session_gen, own_session_gen, statement_id):
        raise HTTPException(status_code=502, detail=detail)

    monkeypatch.setattr(tasks, "process_statement", _boom)

    submitted = await service.submit_extraction_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )

    worker = worker_module.build_worker(job_queue, functions=JOB_FUNCTIONS)
    task = asyncio.create_task(worker.start())
    try:
        for _ in range(100):
            await asyncio.sleep(0.1)
            status = await get_task_status(submitted.job_id)
            if status.state in (TaskState.SUCCEEDED.value, TaskState.FAILED.value):
                break
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert status.state == TaskState.FAILED.value
    assert status.error == detail
    assert status.result is None


async def test_normalization_result_matches_the_blocking_endpoints_body(
    job_queue, backend_session_gen, own_session_gen, monkeypatch
):
    """SC-004 for the normalize step: same content, delivered differently."""
    from app.features.ingestion import tasks
    from app.features.ingestion.schemas import NormalizeStatementResult

    blocking = NormalizeStatementResult(
        normalized_json={
            "bank_name": "National Bank of Egypt",
            "account_number": "4213010248203200016",
            "transactions": [
                {"transaction_date": "2026-05-01", "amount": 1234.56, "merchant_raw": "Carrefour"}
            ],
        },
        model_used="gpt-4o-mini",
    )

    async def _fake_normalize(session_gen, own_session_gen, ocr_result_id):
        return blocking

    monkeypatch.setattr(tasks, "normalize_statement", _fake_normalize)

    submitted = await service.submit_normalization_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )
    status = await _drain(job_queue, submitted.job_id)

    assert status.state == TaskState.SUCCEEDED.value
    assert status.result == blocking.model_dump(mode="json")


async def test_a_job_queued_before_any_worker_exists_still_runs(
    job_queue, backend_session_gen, own_session_gen, monkeypatch
):
    """FR-009's resume case: work waiting when the process died is not lost.

    Submitting with no worker running, then starting one, is the same situation the
    queue is in after a restart.
    """
    from app.features.ingestion import tasks

    class _Result:
        def model_dump(self, mode=None):
            return {"prefix": "resumed/", "ocr_engine": "MinerU", "confidence_score": 1.0}

    async def _fake_process(session_gen, own_session_gen, statement_id):
        return _Result()

    monkeypatch.setattr(tasks, "process_statement", _fake_process)

    submitted = await service.submit_extraction_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )
    queued = await get_task_status(submitted.job_id)
    assert queued.state == TaskState.QUEUED.value

    status = await _drain(job_queue, submitted.job_id)

    assert status.state == TaskState.SUCCEEDED.value, "queued work must survive, not be discarded"
    assert status.result["prefix"] == "resumed/"


async def test_one_failing_job_does_not_stop_the_others(
    job_queue, backend_session_gen, own_session_gen, monkeypatch
):
    """FR-018: a failure inside one job is contained to that job."""
    from fastapi import HTTPException

    from app.features.ingestion import tasks

    doomed = "3f8a1c2e-0000-4000-8000-0000000000ff"

    class _Result:
        def model_dump(self, mode=None):
            return {"prefix": "ok/", "ocr_engine": "MinerU", "confidence_score": 1.0}

    async def _selective(session_gen, own_session_gen, statement_id):
        if statement_id == doomed:
            raise HTTPException(status_code=502, detail="document processing engine failed: x")
        return _Result()

    monkeypatch.setattr(tasks, "process_statement", _selective)

    bad = await job_queue.enqueue("ingestion.process", statement_id=doomed, timeout=0, ttl=JOB_TTL)
    good = await job_queue.enqueue(
        "ingestion.process", statement_id=STATEMENT_ID, timeout=0, ttl=JOB_TTL
    )

    worker = worker_module.build_worker(job_queue, functions=JOB_FUNCTIONS)
    task = asyncio.create_task(worker.start())
    try:
        for _ in range(100):
            await asyncio.sleep(0.1)
            bad_status = await get_task_status(bad.key)
            good_status = await get_task_status(good.key)
            terminal = {TaskState.SUCCEEDED.value, TaskState.FAILED.value}
            if bad_status.state in terminal and good_status.state in terminal:
                break
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert bad_status.state == TaskState.FAILED.value
    assert good_status.state == TaskState.SUCCEEDED.value


async def test_sweep_deletes_a_terminal_job_once_its_retention_window_passes(
    job_queue, backend_session_gen, own_session_gen, own_pg
):
    """FR-016 — this assertion is the whole of the retention requirement."""
    from sqlalchemy import text

    submitted = await service.submit_extraction_job(
        backend_session_gen, own_session_gen, STATEMENT_ID
    )
    job = await job_queue.job(submitted.job_id)
    await job_queue.finish(job, Status.COMPLETE, result={"ok": True, "result": {}})

    async with own_pg() as session:
        await session.execute(
            text("UPDATE saq_jobs SET expire_at = extract(epoch from now()) - 1 WHERE key = :k"),
            {"k": submitted.job_id},
        )
        await session.commit()

    await job_queue.sweep()

    assert await job_queue.job(submitted.job_id) is None
    with pytest.raises(TaskNotFoundError):
        await get_task_status(submitted.job_id)


async def test_job_orphaned_by_a_crash_is_swept_to_failed_not_left_running(
    job_queue, own_session_gen, monkeypatch
):
    """FR-009 / SC-005: a job executing when the process dies becomes terminal.

    The orphaning is real rather than simulated — `queue.update()` resets `touched` to
    now, so a hand-written stale heartbeat is immediately undone. The worker task is
    cancelled mid-job instead, which is what a crash looks like to the queue.

    A one-second `heartbeat` is used here in place of the production constant so the
    sweep has something to reclaim within a test's patience; the mechanism under test is
    identical.

    No worker runs. That is deliberate and is what a SIGKILL looks like: on an *orderly*
    shutdown SAQ re-queues its in-flight jobs instead, so running and cancelling a worker
    would exercise the retry path rather than the sweep.
    """
    job = await job_queue.enqueue(
        "ingestion.process",
        statement_id=STATEMENT_ID,
        timeout=0,
        heartbeat=1,
        retries=1,
        ttl=JOB_TTL,
    )

    # Claim it the way a worker would, then stop touching it. `attempts` matters: the
    # sweep retries a stuck job while `retries > attempts`, so a job orphaned *before*
    # anyone ran it resumes (the amended FR-009's queued case), while one orphaned
    # mid-execution — attempted once, with retries=1 — is aborted instead.
    # `status` must be passed explicitly: update() otherwise re-reads the stored status
    # and overwrites whatever was set on the instance.
    job.started = now()
    job.attempts = 1
    await job_queue.update(job, status=Status.ACTIVE)

    await asyncio.sleep(1.5)  # let the heartbeat window lapse
    await job_queue.sweep()

    status = await get_task_status(job.key)
    assert status.state == TaskState.FAILED.value, "an orphaned job must not read as running"
    assert status.error == SWEPT_ERROR_MESSAGE
