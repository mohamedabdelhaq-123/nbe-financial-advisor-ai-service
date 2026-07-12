"""Analytics service — orchestrates post-ingestion pipeline."""

from app.features.analytics.jobs.anomaly_detection import detect_anomalies
from app.features.analytics.jobs.monthly_summary import compute_monthly_summary
from app.features.analytics.jobs.recurring_charges import detect_recurring_charges
from app.features.analytics.schemas import PostIngestionRequest


async def run_post_ingestion(
    session_gen,
    embed_fn=None,
    req: PostIngestionRequest | None = None,
) -> dict:
    if req is None:
        return {"summary": None, "recurring_charges": [], "anomalies": []}

    summary = await compute_monthly_summary(
        session_gen=session_gen,
        embed_fn=embed_fn,
        user_id=req.user_id,
        account_id=req.account_id,
        month=req.month,
    )

    recurring = await detect_recurring_charges(
        session_gen=session_gen,
        user_id=req.user_id,
        account_id=req.account_id,
    )

    anomalies = await detect_anomalies(
        session_gen=session_gen,
        user_id=req.user_id,
        account_id=req.account_id,
        month=req.month,
    )

    return {
        "summary": summary.model_dump(),
        "recurring_charges": [r.model_dump() for r in recurring],
        "anomalies": [a.model_dump() for a in anomalies],
    }
