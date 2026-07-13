"""Analytics request/response schemas."""

from pydantic import BaseModel, ConfigDict, Field


class MonthlySummaryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"user_id": "1001", "account_id": "5001", "month": "2026-06"}]
        }
    )

    user_id: str = Field(description="Backend user ID to summarize.", examples=["1001"])
    account_id: str = Field(description="Backend account ID to summarize.", examples=["5001"])
    month: str = Field(description="Target month, `YYYY-MM`.", examples=["2026-06"])


class AnomalyCheckRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"user_id": "1001", "account_id": "5001", "month": "2026-06"}]
        }
    )

    user_id: str = Field(
        description="Backend user ID to check for spending anomalies.", examples=["1001"]
    )
    account_id: str = Field(description="Backend account ID to check.", examples=["5001"])
    month: str = Field(description="Target month, `YYYY-MM`.", examples=["2026-06"])


class PostIngestionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"user_id": "1001", "account_id": "5001", "month": "2026-06"}]
        }
    )

    user_id: str = Field(
        description="Backend user ID whose statement was just ingested.", examples=["1001"]
    )
    account_id: str = Field(
        description="Backend account ID the statement belongs to.", examples=["5001"]
    )
    month: str = Field(
        description="Statement month to run all pipelines for, `YYYY-MM`.", examples=["2026-06"]
    )


class MonthlySummaryResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "1001",
                    "account_id": "5001",
                    "month": "2026-06",
                    "total_income": 15000.0,
                    "total_expense": 9200.5,
                    "net": 5799.5,
                    "by_category": {"groceries": 1200.0, "rent": 4000.0},
                    "embedding": [0.012, -0.034, 0.056],
                }
            ]
        }
    )

    user_id: str = Field(description="Backend user ID this summary covers.")
    account_id: str = Field(description="Backend account ID this summary covers.")
    month: str = Field(description="Month this summary covers, `YYYY-MM`.")
    total_income: float = Field(description="Sum of all income transactions for the month.")
    total_expense: float = Field(description="Sum of all expense transactions for the month.")
    net: float = Field(description="`total_income - total_expense` for the month.")
    by_category: dict = Field(description="Total expense amount keyed by spending category.")
    embedding: list[float] = Field(
        description="Vector embedding of the monthly summary, stored for similarity search."
    )


class RecurringChargeResult(BaseModel):
    user_id: str = Field(description="Backend user ID this recurring charge belongs to.")
    account_id: str = Field(description="Backend account ID this recurring charge belongs to.")
    merchant: str = Field(description="Merchant name the charge recurs at.", examples=["Netflix"])
    amount: float = Field(description="Typical charge amount.", examples=[15.99])
    cadence_days: int = Field(
        description="Approximate number of days between charges.", examples=[30]
    )


class AnomalyFlagResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "1001",
                    "account_id": "5001",
                    "category": "dining",
                    "month": "2026-06",
                    "amount": 850.0,
                    "reason": "Amount is outside the IQR-based expected range for this category.",
                }
            ]
        }
    )

    user_id: str = Field(description="Backend user ID this anomaly was detected for.")
    account_id: str = Field(description="Backend account ID this anomaly was detected for.")
    category: str = Field(description="Spending category the anomaly was found in.")
    month: str = Field(description="Month the anomaly occurred in, `YYYY-MM`.")
    amount: float = Field(description="The flagged transaction amount.")
    reason: str = Field(description="Plain-language explanation of why this amount was flagged.")


class PostIngestionResult(BaseModel):
    """Combined result of running all three analytics pipelines after ingestion."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "summary": {
                        "user_id": "1001",
                        "account_id": "5001",
                        "month": "2026-06",
                        "total_income": 15000.0,
                        "total_expense": 9200.5,
                        "net": 5799.5,
                        "by_category": {"groceries": 1200.0, "rent": 4000.0},
                        "embedding": [0.012, -0.034, 0.056],
                    },
                    "recurring_charges": [],
                    "anomalies": [],
                }
            ]
        }
    )

    summary: MonthlySummaryResult | None = Field(
        description="Monthly summary, or null if no summary could be computed."
    )
    recurring_charges: list[RecurringChargeResult] = Field(
        description="Detected recurring charges for the account/month."
    )
    anomalies: list[AnomalyFlagResult] = Field(
        description="Detected spending anomalies for the account/month."
    )
