"""Budget planning request/response schemas."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PlanQuestion(BaseModel):
    id: str = Field(
        description="Stable identifier for this questionnaire question.", examples=["housing_cost"]
    )
    text: str = Field(
        description="The question text to present to the user.",
        examples=["What is your average monthly housing cost?"],
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

    user_context: dict = Field(description="Known financial context about the user so far.")
    answers: dict = Field(description="Answers collected so far, keyed by question ID.")
    questions_asked: int = Field(description="Number of questions already asked in this session.")


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

    user_context: dict = Field(description="Known financial context about the user.")
    answers: dict = Field(description="All questionnaire answers collected for this user.")


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
