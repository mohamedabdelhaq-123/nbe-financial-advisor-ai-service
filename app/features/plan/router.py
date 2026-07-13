"""Budget planning HTTP surface."""

from fastapi import APIRouter, Depends

from app.core.security import ERROR_RESPONSES, require_token
from app.features.plan.schemas import (
    GeneratePlanRequest,
    GeneratePlanResponse,
    NextQuestionRequest,
    NextQuestionResponse,
)
from app.features.plan.service import generate_plan, next_question

router = APIRouter(
    prefix="/internal/plan",
    tags=["plan"],
    dependencies=[Depends(require_token)],
)


@router.post(
    "/question",
    response_model=NextQuestionResponse,
    responses={**ERROR_RESPONSES},
)
async def plan_question(body: NextQuestionRequest):
    """Return the next budget-questionnaire question, or null once it's complete."""
    result = await next_question(
        user_context=body.user_context,
        answers=body.answers,
        questions_asked=body.questions_asked,
    )
    if result is None:
        return {"question": None}
    return {"question": result.model_dump()}


@router.post(
    "/generate",
    response_model=GeneratePlanResponse,
    responses={**ERROR_RESPONSES},
)
async def plan_generate(body: GeneratePlanRequest):
    """Generate a full budget allocation (categories summing to 100%) from questionnaire answers."""
    allocations = await generate_plan(
        user_context=body.user_context,
        answers=body.answers,
    )
    return GeneratePlanResponse(allocations=allocations)
