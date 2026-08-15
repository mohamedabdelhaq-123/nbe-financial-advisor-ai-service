"""Generic status read over the shared SAQ queue.

SAQ owns the job record — status, timestamps, result, retention. The one thing SAQ can't
answer on its own is what its seven statuses mean in this API's four; `derive_state()` is
that mapping, and it is pure so the whole decision table is testable without a queue.

Submission and dedup are not here — they require knowing what a "target" means for a
given feature's jobs, which is feature-specific by construction. Any job the queue knows
about can be reported generically, regardless of which feature enqueued it.
"""

from datetime import UTC, datetime

from saq.job import Status

from app.core.tasks.queue import SWEPT_ERROR_MESSAGE, get_queue
from app.core.tasks.schemas import TaskState, TaskStatusResponse, epoch_ms_to_datetime

INTERNAL_FAILURE_MESSAGE = "job failed with an internal error"
"""What a caller sees when a job raised something unexpected.

SAQ stores the stack trace in `Job.error`; traces stay in the logs rather than being
returned over the wire.
"""


class TaskNotFoundError(Exception):
    """Raised when a job reference is unknown — never enqueued, or aged out."""


def derive_state(
    status: Status, result: object, error: str | None
) -> tuple[TaskState, dict | None, str | None]:
    """Map SAQ's seven statuses plus the job's envelope onto the contract's four states.

    Pure by design: the status surface's whole decision table is testable without a queue,
    a database, or a running worker.
    """
    if status in (Status.NEW, Status.QUEUED):
        return TaskState.QUEUED, None, None
    if status == Status.ACTIVE:
        return TaskState.RUNNING, None, None
    if status == Status.COMPLETE:
        if isinstance(result, dict) and result.get("ok") is True:
            payload = result.get("result")
            return TaskState.SUCCEEDED, payload if isinstance(payload, dict) else None, None
        if isinstance(result, dict) and result.get("ok") is False:
            return TaskState.FAILED, None, str(result.get("error") or INTERNAL_FAILURE_MESSAGE)
        # Completed without a recognisable envelope — treat as a failure rather than
        # reporting success with nothing to hand back.
        return TaskState.FAILED, None, INTERNAL_FAILURE_MESSAGE
    # FAILED / ABORTED / ABORTING. The sweep's message is the one `error` value written by
    # SAQ that is safe to surface; anything else is a stack trace.
    if error == SWEPT_ERROR_MESSAGE:
        return TaskState.FAILED, None, SWEPT_ERROR_MESSAGE
    return TaskState.FAILED, None, INTERNAL_FAILURE_MESSAGE


async def get_task_status(job_key: str) -> TaskStatusResponse:
    """Read a job's current state. Repeatable and non-destructive."""
    job = await get_queue().job(job_key)
    if job is None:
        raise TaskNotFoundError(job_key)

    state, result, error = derive_state(job.status, job.result, job.error)
    return TaskStatusResponse(
        job_id=job.key,
        function=job.function,
        state=state.value,
        submitted_at=epoch_ms_to_datetime(job.queued) or datetime.now(UTC),
        started_at=epoch_ms_to_datetime(job.started),
        finished_at=epoch_ms_to_datetime(job.completed),
        result=result,
        error=error,
    )
