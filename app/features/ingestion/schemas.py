"""Request/response contracts for the ingestion slice."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProcessStatementRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"statement_id": "b3f1c2d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"}]}
    )

    statement_id: UUID = Field(
        description="Backend statement ID of a previously uploaded document to extract."
    )


class ProcessStatementResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "prefix": "statements/1001/b3f1c2d4/",
                    "ocr_engine": "mineru",
                    "confidence_score": 1.0,
                }
            ]
        }
    )

    prefix: str = Field(
        description="Object-storage key prefix under which the extracted artifacts were saved."
    )
    ocr_engine: str = Field(description="Identifier of the OCR engine that performed extraction.")
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Extraction confidence in [0.0, 1.0]; always 1.0 on success.",
    )


class NormalizeStatementRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"ocr_result_id": "c4d5e6f7-8a9b-0c1d-2e3f-4a5b6c7d8e9f"}]}
    )

    ocr_result_id: UUID = Field(
        description="ID of a previously processed statement's OCR result to normalize."
    )


class NormalizeStatementResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "normalized_json": {
                        "transactions": [
                            {"date": "2026-06-03", "amount": -45.20, "description": "Groceries"}
                        ]
                    },
                    "model_used": "gpt-4o-mini",
                }
            ]
        }
    )

    normalized_json: dict = Field(
        description="Structured transactions extracted from the statement's OCR content."
    )
    model_used: str = Field(description="Identifier of the LLM that performed normalization.")


class JobStep(StrEnum):
    """Which pipeline step an asynchronous ingestion job performs."""

    PROCESS = "process"
    NORMALIZE = "normalize"


class JobSubmissionResponse(BaseModel):
    """Acknowledgment for an asynchronous ingestion submission.

    A deliberately different contract from `app.core.tasks.schemas.TaskStatusResponse`:
    `step` only makes sense for ingestion's two pipeline steps, so this stays
    ingestion-owned rather than folded into the generic status schema.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "7f1a9c30-2b44-4d51-9a2e-6c8b0f3d1e77",
                    "step": "process",
                    "state": "queued",
                    "submitted_at": "2026-07-28T09:14:03.221Z",
                }
            ]
        }
    )

    job_id: str = Field(
        description=(
            "Opaque job reference for later status reads. Treat as a string; its format "
            "is the job runner's business."
        )
    )
    step: str = Field(description="Pipeline step this job performs: 'process' or 'normalize'.")
    state: str = Field(
        description=(
            "'queued' for a newly accepted job; may already be 'running' when a repeat "
            "submission resolved to a job that is already executing."
        )
    )
    submitted_at: datetime = Field(
        description=(
            "When the job this reference points at was submitted — the original "
            "submission time when a repeat submission was deduplicated."
        )
    )
