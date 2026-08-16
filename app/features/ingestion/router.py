"""Ingestion slice HTTP surface."""

from fastapi import APIRouter, Depends

from app.backend_db import get_backend_session
from app.core.db import get_own_session
from app.core.security import ERROR_RESPONSES, require_token
from app.features.ingestion.schemas import (
    JobSubmissionResponse,
    NormalizeStatementRequest,
    NormalizeStatementResult,
    ProcessStatementRequest,
    ProcessStatementResult,
)
from app.features.ingestion.service import (
    normalize_statement,
    process_statement,
    submit_extraction_job,
    submit_normalization_job,
)

_TARGET_NOT_FOUND: dict[int | str, dict] = {
    404: {
        "description": "The submitted statement or OCR result does not exist; no job is created.",
        "content": {"application/json": {"example": {"detail": "statement not found"}}},
    }
}

router = APIRouter(
    prefix="/internal/ingestion",
    tags=["ingestion"],
    dependencies=[Depends(require_token)],
)


@router.post(
    "/process",
    response_model=ProcessStatementResult,
    responses={**ERROR_RESPONSES},
)
async def process(body: ProcessStatementRequest) -> ProcessStatementResult:
    """Extract a previously uploaded statement's content via MinerU. Requires a Bearer token."""
    return await process_statement(
        session_gen=get_backend_session,
        own_session_gen=get_own_session,
        statement_id=str(body.statement_id),
    )


@router.post(
    "/normalize",
    response_model=NormalizeStatementResult,
    responses={**ERROR_RESPONSES},
)
async def normalize(body: NormalizeStatementRequest) -> NormalizeStatementResult:
    """Extract structured transactions from a previously processed statement's OCR content.

    Requires a Bearer token.
    """
    return await normalize_statement(
        session_gen=get_backend_session,
        own_session_gen=get_own_session,
        ocr_result_id=str(body.ocr_result_id),
    )


@router.post(
    "/jobs/process",
    response_model=JobSubmissionResponse,
    status_code=202,
    responses={**ERROR_RESPONSES, **_TARGET_NOT_FOUND},
)
async def submit_process_job(body: ProcessStatementRequest) -> JobSubmissionResponse:
    """Submit extraction for a previously uploaded statement and return a job reference.

    Acknowledges before the extraction runs; poll `GET /internal/tasks/{job_id}` for the
    outcome. Submitting a statement that already has a job in flight returns that job's
    reference instead of starting a second execution.
    """
    return await submit_extraction_job(
        session_gen=get_backend_session,
        own_session_gen=get_own_session,
        statement_id=str(body.statement_id),
    )


@router.post(
    "/jobs/normalize",
    response_model=JobSubmissionResponse,
    status_code=202,
    responses={**ERROR_RESPONSES, **_TARGET_NOT_FOUND},
)
async def submit_normalize_job(body: NormalizeStatementRequest) -> JobSubmissionResponse:
    """Submit normalization for a previously extracted statement and return a job reference.

    Same submit-and-poll terms as `/jobs/process`; poll `GET /internal/tasks/{job_id}`
    for the outcome. The two steps deduplicate independently, so an in-flight extraction
    never suppresses a normalization.
    """
    return await submit_normalization_job(
        session_gen=get_backend_session,
        own_session_gen=get_own_session,
        ocr_result_id=str(body.ocr_result_id),
    )
