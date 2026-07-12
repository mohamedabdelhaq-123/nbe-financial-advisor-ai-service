"""Budget planning HTTP surface."""

from fastapi import APIRouter, Depends

from app.core.security import require_token
from app.features.plan.schemas import (
    GeneratePlanRequest,
    GeneratePlanResponse,
    NextQuestionRequest,
)
from app.features.plan.service import generate_plan, next_question

router = APIRouter(
    prefix="/internal/plan",
    tags=["plan"],
    dependencies=[Depends(require_token)],
)


@router.post("/question")
async def plan_question(body: NextQuestionRequest):
    result = await next_question(
        user_context=body.user_context,
        answers=body.answers,
        questions_asked=body.questions_asked,
    )
    if result is None:
        return {"question": None}
    return {"question": result.model_dump()}


@router.post("/generate")
async def plan_generate(body: GeneratePlanRequest):
    allocations = await generate_plan(
        user_context=body.user_context,
        answers=body.answers,
    )
    return GeneratePlanResponse(allocations=allocations)
