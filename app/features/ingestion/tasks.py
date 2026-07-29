"""The two SAQ job functions ingestion contributes to the shared worker.

Each calls the *existing* blocking pipeline service unchanged. That is what makes the
async path's result content, diagnostic detail, and audit rows identical to the blocking
path — none of it is reimplemented here, so none of it can drift.

Both return a JSON envelope rather than raising for expected failures. SAQ stores a
raised exception's stack trace in `Job.error`, which is not something to hand a caller;
the envelope carries the same human-readable detail the blocking endpoint puts in its
HTTP response instead. Genuinely unexpected exceptions are left to propagate, so SAQ
records them as failures with the trace intact for operators.
"""

from typing import Any

from fastapi import HTTPException
from saq.types import Context, FunctionsType

from app.backend_db import get_backend_session
from app.core.db import get_own_session
from app.core.logging import get_logger
from app.features.ingestion.service import normalize_statement, process_statement

logger = get_logger(__name__)

PROCESS_JOB = "ingestion.process"
NORMALIZE_JOB = "ingestion.normalize"


def _ok(result: Any) -> dict:
    return {"ok": True, "result": result}


def _failed(detail: str) -> dict:
    return {"ok": False, "error": detail}


async def process_job(ctx: Context, *, statement_id: str) -> dict:
    """Extract a statement's content — the async form of `POST /internal/ingestion/process`."""
    # Job payloads carry statement content; only identifiers and outcomes are logged.
    logger.info("ingestion_job_started", step="process", statement_id=statement_id)
    try:
        result = await process_statement(
            session_gen=get_backend_session,
            own_session_gen=get_own_session,
            statement_id=statement_id,
        )
    except HTTPException as exc:
        logger.warning("ingestion_job_failed", step="process", statement_id=statement_id)
        return _failed(str(exc.detail))
    logger.info("ingestion_job_succeeded", step="process", statement_id=statement_id)
    return _ok(result.model_dump(mode="json"))


async def normalize_job(ctx: Context, *, ocr_result_id: str) -> dict:
    """Normalize an OCR result — the async form of `POST /internal/ingestion/normalize`."""
    logger.info("ingestion_job_started", step="normalize", ocr_result_id=ocr_result_id)
    try:
        result = await normalize_statement(
            session_gen=get_backend_session,
            own_session_gen=get_own_session,
            ocr_result_id=ocr_result_id,
        )
    except HTTPException as exc:
        logger.warning("ingestion_job_failed", step="normalize", ocr_result_id=ocr_result_id)
        return _failed(str(exc.detail))
    logger.info("ingestion_job_succeeded", step="normalize", ocr_result_id=ocr_result_id)
    return _ok(result.model_dump(mode="json"))


# Annotated rather than inferred: the two job functions take different keyword
# arguments, so an unannotated list would be typed from whichever came first.
JOB_FUNCTIONS: FunctionsType[Context] = [
    (PROCESS_JOB, process_job),
    (NORMALIZE_JOB, normalize_job),
]
"""Job functions this slice contributes to the shared worker.

Registered under explicit names rather than SAQ's default of `__qualname__`, so renaming
a Python function can't orphan jobs already queued under the old name.
"""
