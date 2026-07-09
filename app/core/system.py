"""Operational probes — liveness and readiness.

These require no auth and make no external calls, so container healthchecks and
orchestrators can hit them cheaply and safely.
"""

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    """Readiness probe."""
    return {"ready": True}
