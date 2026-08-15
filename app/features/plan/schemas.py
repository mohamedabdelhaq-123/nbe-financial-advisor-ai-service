"""Budget planning request/response schemas."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PlanQuestion(BaseModel):
    id: str = Field(
        description="Stable identifier for this questionnaire question.", examples=["housing_cost"]
    )
    text: str = Field(
        description="The question text to present to the user.",
        examples=["What is your average monthly housing cost?"],
    )
    kind: Literal["yes_no", "numeric", "enum", "free_text"] = Field(
        default="free_text",
        description="The expected answer shape, used to validate a reply to this question.",
    )
    choices: list[str] | None = Field(
        default=None, description="Allowed values when kind == 'enum'."
    )
    min_value: float | None = Field(
        default=None, description="Inclusive lower bound when kind == 'numeric'."
    )
    max_value: float | None = Field(
        default=None, description="Inclusive upper bound when kind == 'numeric'."
    )
    default: str | None = Field(
        default=None,
        description=(
            "Fallback value used if MAX_VALIDATION_ATTEMPTS is exhausted for a "
            "constrained (non-free_text) question."
        ),
    )


class AnswerValidation(BaseModel):
    valid: bool = Field(description="Whether the raw answer is an acceptable reply.")
    normalized_value: str | None = Field(
        default=None, description="The answer normalized for storage, when valid."
    )
    reason: str | None = Field(
        default=None,
        description=(
            "Shown to the user in place of a rejection message when invalid — must "
            "actively help them answer (e.g. clarify what's being asked), not just "
            "name the problem."
        ),
    )


class BudgetAllocation(BaseModel):
    category: str = Field(description="Budget category name.", examples=["housing"])
    percentage: Decimal = Field(
        description="Share of the budget allocated to this category, as a percentage.",
        examples=[Decimal("30.0")],
    )


class NextQuestionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_context": {"monthly_income": 15000},
                    "answers": {"housing_cost": 4000},
                    "questions_asked": 1,
                }
            ]
        }
    )

    user_context: dict = Field(
        description=(
            "Deprecated — no longer used. Real context is now derived from `user_id`'s "
            "transaction history when provided (see app.features.plan.context)."
        )
    )
    answers: dict = Field(description="Answers collected so far, keyed by question ID.")
    questions_asked: int = Field(description="Number of questions already asked in this session.")
    user_id: UUID | None = Field(
        default=None,
        description="When provided, real per-user financial context is derived and used to "
        "personalize/skip questions. Omit to fall back to the generic questionnaire.",
    )


class GeneratePlanRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_context": {"monthly_income": 15000},
                    "answers": {"housing_cost": 4000, "transportation_cost": 800},
                }
            ]
        }
    )

    user_context: dict = Field(
        description=(
            "Deprecated — no longer used. Real context is now derived from `user_id`'s "
            "transaction history when provided (see app.features.plan.context)."
        )
    )
    answers: dict = Field(description="All questionnaire answers collected for this user.")
    user_id: UUID | None = Field(
        default=None,
        description="When provided, real per-user financial context is derived and threaded "
        "into plan generation. Omit to fall back to the generic prompt.",
    )


class NextQuestionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "question": {
                        "id": "housing_cost",
                        "text": "What is your average monthly housing cost?",
                    }
                },
                {"question": None},
            ]
        }
    )

    question: PlanQuestion | None = Field(
        description="The next questionnaire question, or null if the questionnaire is complete."
    )


class GeneratePlanResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "allocations": [
                        {"category": "housing", "percentage": "30.0"},
                        {"category": "savings", "percentage": "20.0"},
                    ]
                }
            ]
        }
    )

    allocations: list[BudgetAllocation] = Field(
        description="Budget allocations across categories; percentages sum to 100."
    )
