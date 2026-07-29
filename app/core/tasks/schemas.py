"""Generic response contract for reading a job's status.

Submission is deliberately not modeled here — what a job's "target" is, and what its
request body looks like, is feature-specific. This module only covers what every job
shares regardless of who submitted it: an opaque reference, a coarse state, timestamps,
and a result/error envelope.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TaskState(StrEnum):
    """The four states the caller-facing contract exposes.

    Derived from SAQ's seven-value `Status` plus the job's result envelope; see
    `service.derive_state()`. Nothing persists these — they are computed per read.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def epoch_ms_to_datetime(value: int | None) -> datetime | None:
    """Convert a SAQ timestamp to an aware UTC datetime.

    SAQ stores milliseconds since the epoch (`saq.utils.now()`), and uses 0 rather than
    null for "hasn't happened yet".
    """
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "7f1a9c30-2b44-4d51-9a2e-6c8b0f3d1e77",
                    "function": "ingestion.process",
                    "state": "succeeded",
                    "submitted_at": "2026-07-28T09:14:03.221Z",
                    "started_at": "2026-07-28T09:14:03.402Z",
                    "finished_at": "2026-07-28T09:21:47.918Z",
                    "result": {
                        "prefix": "pfm-statements-ocr/b3f1c2d4/",
                        "ocr_engine": "MinerU",
                        "confidence_score": 1.0,
                    },
                    "error": None,
                }
            ]
        }
    )

    job_id: str = Field(
        description=(
            "Opaque job reference this status was read with. Treat as a string; its "
            "format is the job runner's business."
        )
    )
    function: str = Field(
        description=(
            "The job's registered function name (e.g. 'ingestion.process'). Identifies "
            "what kind of work this is; a caller that only submits one kind can ignore it."
        )
    )
    state: str = Field(description="One of: queued, running, succeeded, failed.")
    submitted_at: datetime = Field(description="When the job was submitted.")
    started_at: datetime | None = Field(
        default=None, description="When execution began; null while queued."
    )
    finished_at: datetime | None = Field(
        default=None, description="When the job reached a terminal state; null until then."
    )
    result: dict | None = Field(
        default=None,
        description=(
            "Present only when state is 'succeeded'. Shape is specific to the function "
            "that ran, identical to whatever that feature's blocking equivalent returns."
        ),
    )
    error: str | None = Field(
        default=None,
        description=(
            "Present only when state is 'failed'. Carries the same diagnostic detail the "
            "job's own failure path reports."
        ),
    )
