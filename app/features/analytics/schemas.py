"""Analytics request/response schemas."""

from pydantic import BaseModel


class MonthlySummaryRequest(BaseModel):
    user_id: str
    account_id: str
    month: str


class AnomalyCheckRequest(BaseModel):
    user_id: str
    account_id: str
    month: str


class PostIngestionRequest(BaseModel):
    user_id: str
    account_id: str
    month: str


class MonthlySummaryResult(BaseModel):
    user_id: str
    account_id: str
    month: str
    total_income: float
    total_expense: float
    net: float
    by_category: dict
    embedding: list[float]


class RecurringChargeResult(BaseModel):
    user_id: str
    account_id: str
    merchant: str
    amount: float
    cadence_days: int


class AnomalyFlagResult(BaseModel):
    user_id: str
    account_id: str
    category: str
    month: str
    amount: float
    reason: str
