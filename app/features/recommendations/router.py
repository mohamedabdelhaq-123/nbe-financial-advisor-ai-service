"""Recommendation HTTP surface."""

from fastapi import APIRouter, Depends

from app.core.db import get_own_session
from app.core.security import require_token
from app.features.recommendations.schemas import MatchRequest, MatchResponse
from app.features.recommendations.service import match

router = APIRouter(
    prefix="/internal/recommendations",
    tags=["recommendations"],
    dependencies=[Depends(require_token)],
)


@router.post("/match", response_model=MatchResponse)
async def recommendation_match(body: MatchRequest):
    async for session in get_own_session():
        results = await match(
            session=session,
            user_id=body.user_id,
            query=body.query,
            top_k=body.top_k,
        )
        return MatchResponse(matches=results)
