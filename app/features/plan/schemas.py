"""Budget planning request/response schemas."""

from decimal import Decimal

from pydantic import BaseModel


class PlanQuestion(BaseModel):
    id: str
    text: str


class BudgetAllocation(BaseModel):
    category: str
    percentage: Decimal


class NextQuestionRequest(BaseModel):
    user_context: dict
    answers: dict
    questions_asked: int


class GeneratePlanRequest(BaseModel):
    user_context: dict
    answers: dict


class GeneratePlanResponse(BaseModel):
    allocations: list[BudgetAllocation]
