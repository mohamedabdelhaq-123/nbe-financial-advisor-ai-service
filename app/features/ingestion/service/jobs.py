"""Submission and deduplication for the ingestion job surface.

There is no job table here. SAQ's `saq_jobs` is the record — status, timestamps, result,
retention — and everything below is derived from it. The one thing SAQ can't answer on
its own is handled explicitly: whether a target already has work in flight (§`_live_job`).
Reading a job's current state back is generic and lives in `app.core.tasks.service`
instead — it needs nothing ingestion-specific.

The queue and worker themselves are infrastructure and live in `app.core.tasks`; this
module supplies submission entry points for the router and `JOB_FUNCTIONS` (in
`app.features.ingestion.tasks`) for the app to register at startup.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from saq.job import Job, Status
from sqlalchemy import select, text

from app.backend_db.models import StatementFile, StatementOcrResult
from app.core.tasks.queue import get_queue
from app.core.tasks.schemas import TaskState, epoch_ms_to_datetime
from app.core.tasks.service import derive_state
from app.features.ingestion.schemas import JobStep, JobSubmissionResponse
from app.features.ingestion.tasks import NORMALIZE_JOB, PROCESS_JOB

# --- per-job settings ------------------------------------------------------
# Each overrides a SAQ default that is wrong for *this* feature's jobs. The default is
# named so a reader can tell these apart from arbitrary numbers.

JOB_TIMEOUT = 0
"""No execution time limit (SAQ default: 10 seconds).

Extraction of a multi-page statement runs for minutes; at the default, every real job
would be killed at ten seconds and report as failed for no visible reason.
"""

JOB_TTL = 30 * 24 * 60 * 60
"""How long a finished job's record — including its result — is kept (SAQ default: 600s).

This single value *is* the feature's retention rule: SAQ's sweep deletes terminal jobs
once `expire_at` passes, and there is no second purge process. At the default, results
carrying full transaction detail would vanish ten minutes after completion.
"""

JOB_RETRIES = 1
"""One attempt, no automatic retry (matches SAQ's default; stated because it matters).

A failed step is re-driven by the caller's explicit retry, not by us. Silent re-execution
would also emit a second audit row for one submitted unit of work.
"""

JOB_HEARTBEAT = 30
"""Seconds a running job may go without a heartbeat before the sweep reclaims it
(SAQ default: 0, i.e. disabled).

This is what turns a job orphaned by a crash into a terminal `failed` instead of one that
reads as running forever.
"""

SUBMISSION_LOCK_KEYSPACE = 1
"""First key for advisory locks taken by *submitters* serialising work on one target.

Must differ from SAQ's own advisory-lock keyspace, which defaults to 0
(`PostgresQueue(saq_lock_keyspace=0)`) — sharing it would let a submitter and SAQ's sweep
collide on the same lock.

Ingestion-owned rather than promoted to `app.core.tasks`: it has exactly one caller today
(`_submit`, below). Lift it into core only if a second feature needs the same
serialize-on-target-key pattern.
"""

_LIVE_STATUSES = [Status.NEW, Status.QUEUED, Status.ACTIVE]

_TARGET_KWARG = {PROCESS_JOB: "statement_id", NORMALIZE_JOB: "ocr_result_id"}


async def _statement_exists(session_gen, statement_id: uuid.UUID) -> bool:
    """Existence check only — deliberately projects no columns beyond the id."""
    async for session in session_gen():
        result = await session.execute(
            select(StatementFile.id).where(StatementFile.id == statement_id)
        )
        return result.scalar_one_or_none() is not None
    return False


async def _ocr_result_exists(session_gen, ocr_result_id: uuid.UUID) -> bool:
    async for session in session_gen():
        result = await session.execute(
            select(StatementOcrResult.id).where(StatementOcrResult.id == ocr_result_id)
        )
        return result.scalar_one_or_none() is not None
    return False


def _target_of(job: Job) -> str | None:
    kwarg = _TARGET_KWARG.get(job.function)
    if kwarg is None:
        return None
    value = (job.kwargs or {}).get(kwarg)
    return str(value) if value is not None else None


def _submission_response(job: Job, step: JobStep) -> JobSubmissionResponse:
    state, _, _ = derive_state(job.status, job.result, job.error)
    return JobSubmissionResponse(
        job_id=job.key,
        step=step.value,
        state=state.value,
        submitted_at=epoch_ms_to_datetime(job.queued) or datetime.now(UTC),
    )


async def _live_job(function: str, target_id: str) -> Job | None:
    """Find a non-terminal job for this (step, target), if there is one.

    Scans the queue's own records rather than a table of ours. The scan is bounded by the
    number of jobs that have not finished — the worker's concurrency plus whatever is
    waiting — not by the 30 days of history behind them, because terminal jobs are
    excluded by status.

    A key SAQ no longer knows simply isn't found, which is what lets a retry proceed once
    the previous job has aged out.
    """
    async for job in get_queue().iter_jobs(statuses=_LIVE_STATUSES):
        if job.function == function and _target_of(job) == target_id:
            return job
    return None


async def _submit(
    own_session_gen,
    *,
    step: JobStep,
    target_id: uuid.UUID,
    function: str,
    kwargs: dict,
) -> JobSubmissionResponse:
    """Enqueue work for a target, unless that target already has a job in flight."""
    target = str(target_id)
    group_key = f"{step.value}:{target}"

    async for session in own_session_gen():
        # Serialise submissions for one target. Without this, two simultaneous
        # submissions could both scan, both find nothing, and both enqueue. Transaction
        # scoped, so the commit below releases it.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:keyspace, hashtext(:target))"),
            {"keyspace": SUBMISSION_LOCK_KEYSPACE, "target": group_key},
        )

        live = await _live_job(function, target)
        if live is not None:
            await session.commit()
            return _submission_response(live, step)

        job = await get_queue().enqueue(
            function,
            # Native backstop: SAQ's dequeue skips groups that already have an active
            # job, so even a duplicate that somehow slipped past the lock could never
            # run concurrently with the job it duplicates.
            group_key=group_key,
            timeout=JOB_TIMEOUT,
            ttl=JOB_TTL,
            retries=JOB_RETRIES,
            heartbeat=JOB_HEARTBEAT,
            **kwargs,
        )
        await session.commit()

        if job is None:  # pragma: no cover - only reachable on a key collision
            raise HTTPException(status_code=409, detail="job already enqueued")

        return JobSubmissionResponse(
            job_id=job.key,
            step=step.value,
            state=TaskState.QUEUED.value,
            submitted_at=epoch_ms_to_datetime(job.queued) or datetime.now(UTC),
        )

    raise RuntimeError("own-DB session generator yielded nothing")


async def submit_extraction_job(
    session_gen,
    own_session_gen,
    statement_id: str,
) -> JobSubmissionResponse:
    target_id = uuid.UUID(statement_id)
    if not await _statement_exists(session_gen, target_id):
        raise HTTPException(status_code=404, detail="statement not found")
    return await _submit(
        own_session_gen,
        step=JobStep.PROCESS,
        target_id=target_id,
        function=PROCESS_JOB,
        kwargs={"statement_id": str(target_id)},
    )


async def submit_normalization_job(
    session_gen,
    own_session_gen,
    ocr_result_id: str,
) -> JobSubmissionResponse:
    target_id = uuid.UUID(ocr_result_id)
    if not await _ocr_result_exists(session_gen, target_id):
        raise HTTPException(status_code=404, detail="ocr result not found")
    return await _submit(
        own_session_gen,
        step=JobStep.NORMALIZE,
        target_id=target_id,
        function=NORMALIZE_JOB,
        kwargs={"ocr_result_id": str(target_id)},
    )
