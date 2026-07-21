"""Operational probes — liveness, readiness, and MinerU reachability.

`/health` and `/ready` require no auth and make no external calls, so container
healthchecks and orchestrators can hit them cheaply and safely. `/health/mineru`
is the exception: it deliberately makes one outbound call to MinerU so operators
can confirm the (GPU-backed, ~10-minute cold start) engine is warm before
switching `USE_MOCK_MINERU=0` or before uploading a real statement.
"""

import httpx
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["system"])

_MINERU_HEALTH_TIMEOUT = httpx.Timeout(5.0)


@router.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    """Readiness probe."""
    return {"ready": True}


@router.get("/health/mineru")
async def mineru_health() -> dict:
    """MinerU reachability probe.

    In mock mode (`AI_SERVICE_MINERU__USE_MOCK=1`) reports ready with no network
    call. In real mode it GETs MinerU's own `/health` with a short timeout:
    `ready` is true only on a 200, so a cold/starting or dead endpoint reads
    as not-ready with a `detail` instead of surfacing later as a confusing
    upload failure.
    """
    if settings.mineru.use_mock:
        return {"mode": "mock", "ready": True}

    url = settings.mineru.api_url
    if not url:
        return {"mode": "real", "ready": False, "detail": "MINERU_API_URL is not set"}

    try:
        async with httpx.AsyncClient(timeout=_MINERU_HEALTH_TIMEOUT) as client:
            response = await client.get(f"{url}/health")
        return {
            "mode": "real",
            "ready": response.status_code == 200,
            "url": url,
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {"mode": "real", "ready": False, "url": url, "detail": str(exc)}
