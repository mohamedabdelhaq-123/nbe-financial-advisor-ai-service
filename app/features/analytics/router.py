"""Analytics slice HTTP surface — internal endpoints returning computed results."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends

from app.backend_db import get_backend_session
from app.core.security import require_token
from app.features.analytics.jobs.anomaly_detection import detect_anomalies
from app.features.analytics.jobs.monthly_summary import compute_monthly_summary
from app.features.analytics.schemas import (
    AnomalyCheckRequest,
    MonthlySummaryRequest,
    PostIngestionRequest,
)
from app.features.analytics.service import run_post_ingestion

router = APIRouter(
    prefix="/internal/analyze",
    tags=["analytics"],
    dependencies=[Depends(require_token)],
)

# The jobs below drive `session_gen()` via `async with`, i.e. they expect a
# callable that returns an async context manager (matching the `own_pg`
# Testcontainers fixture's shape in tests). `get_backend_session` is a plain
# async-generator dependency function instead (built for FastAPI's own
# `Depends()` machinery), so calling it directly and entering it with
# `async with` raises `TypeError: 'async_generator' object does not support
# the asynchronous context manager protocol`. Wrapping it once here adapts it
# to the shape the jobs actually need, without changing the jobs or their
# tests.
_backend_session_gen = asynccontextmanager(get_backend_session)


@router.post("/post-ingestion")
async def post_ingestion(body: PostIngestionRequest):
    return await run_post_ingestion(
        session_gen=_backend_session_gen,
        req=body,
    )


@router.post("/monthly-summary")
async def monthly_summary(
    body: MonthlySummaryRequest,
):
    result = await compute_monthly_summary(
        session_gen=_backend_session_gen,
        user_id=body.user_id,
        account_id=body.account_id,
        month=body.month,
    )
    return result.model_dump()


@router.post("/anomaly-check")
async def anomaly_check(body: AnomalyCheckRequest):
    flags = await detect_anomalies(
        session_gen=_backend_session_gen,
        user_id=body.user_id,
        account_id=body.account_id,
        month=body.month,
    )
    return [f.model_dump() for f in flags]
