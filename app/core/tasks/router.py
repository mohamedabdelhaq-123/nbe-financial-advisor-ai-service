"""Generic job-status endpoint over the shared SAQ queue.

One route for every feature's async jobs: submission and dedup are feature-owned (each
feature knows what a "target" means for its own work), but reading a job's current state
back is not — it only needs the job key SAQ already tracks.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import ERROR_RESPONSES, require_token
from app.core.tasks.schemas import TaskStatusResponse
from app.core.tasks.service import TaskNotFoundError, get_task_status

router = APIRouter(
    prefix="/internal/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_token)],
)


@router.get(
    "/{job_id}",
    response_model=TaskStatusResponse,
    responses={
        **ERROR_RESPONSES,
        404: {
            "description": "Unknown job reference, or one whose record has aged out.",
            "content": {"application/json": {"example": {"detail": "job not found"}}},
        },
    },
)
async def read_task(job_id: str) -> TaskStatusResponse:
    """Read a job's state, and its result or failure reason once terminal.

    Repeatable and non-destructive. A job that *failed* is still reported with `200` —
    the read succeeded, the job is what failed; only an unknown reference is a `404`.
    """
    try:
        return await get_task_status(job_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="job not found") from None
