"""Analytics slice HTTP surface — internal endpoints returning computed results."""

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


@router.post("/post-ingestion")
async def post_ingestion(body: PostIngestionRequest):
    return await run_post_ingestion(
        session_gen=get_backend_session,
        req=body,
    )


@router.post("/monthly-summary")
async def monthly_summary(
    body: MonthlySummaryRequest,
):
    result = await compute_monthly_summary(
        session_gen=get_backend_session,
        user_id=body.user_id,
        account_id=body.account_id,
        month=body.month,
    )
    return result.model_dump()


@router.post("/anomaly-check")
async def anomaly_check(body: AnomalyCheckRequest):
    flags = await detect_anomalies(
        session_gen=get_backend_session,
        user_id=body.user_id,
        account_id=body.account_id,
        month=body.month,
    )
    return [f.model_dump() for f in flags]
