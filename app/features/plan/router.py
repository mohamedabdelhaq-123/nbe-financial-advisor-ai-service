"""Budget planning HTTP surface.

No live Django caller exists for either endpoint today (confirmed against
the backend's services/ai_service.py — it's a documented stub). `user_id`
is optional on both request schemas for that reason: when supplied, real
per-user context is derived and used to personalize/skip questions the same
way the chat graph's planner_ask_node does; when omitted, both endpoints
fall back to the generic questionnaire/prompt.
"""

from fastapi import APIRouter, Depends

from app.core.security import ERROR_RESPONSES, require_token
from app.features.plan.context import PlannerContext, derive_planner_context
from app.features.plan.schemas import (
    GeneratePlanRequest,
    GeneratePlanResponse,
    NextQuestionRequest,
    NextQuestionResponse,
)
from app.features.plan.service import generate_plan, infer_answers_from_context, next_question

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
    context: PlannerContext = await derive_planner_context(body.user_id) if body.user_id else {}
    # Same merge planner_ask_node does — explicit answers win over inferred
    # ones, and next_question itself doesn't do this merge internally.
    answers = {**infer_answers_from_context(context), **body.answers}
    result = await next_question(
        context=context,
        answers=answers,
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
    context: PlannerContext = await derive_planner_context(body.user_id) if body.user_id else {}
    allocations = await generate_plan(
        context=context,
        answers=body.answers,
    )
    return GeneratePlanResponse(allocations=allocations)
