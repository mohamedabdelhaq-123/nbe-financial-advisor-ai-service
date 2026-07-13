"""Ingestion slice HTTP surface."""

from fastapi import APIRouter, Depends

from app.backend_db import get_backend_session
from app.core.db import get_own_session
from app.core.security import ERROR_RESPONSES, require_token
from app.features.ingestion.schemas import (
    NormalizeStatementRequest,
    NormalizeStatementResult,
    ProcessStatementRequest,
    ProcessStatementResult,
)
from app.features.ingestion.service import normalize_statement, process_statement

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
