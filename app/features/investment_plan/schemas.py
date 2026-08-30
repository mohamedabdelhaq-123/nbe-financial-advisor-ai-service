from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.features.market_data.schemas import CuratedInstrument, MarketQuote


class InvestmentContext(BaseModel):
    average_monthly_income: Decimal | None = None
    average_monthly_expenses: Decimal | None = None
    monthly_goal_commitment: Decimal = Decimal("0")
    estimated_monthly_surplus: Decimal | None = None
    currency: str | None = None
    months_used: int = 0
    current_balance: Decimal | None = None
    current_balance_currency: str | None = None
    instruments: list[CuratedInstrument] = Field(default_factory=list)


class InvestmentAllocation(BaseModel):
    instrument_id: uuid.UUID
    instrument_code: str
    display_name: str
    asset_class: str
    percentage: Decimal
    target_amount: Decimal
    unit_price: Decimal
    price_currency: str
    unit: str
    price_type: str
    minimum_increment: Decimal
    quantity: Decimal
    actual_allocated_amount: Decimal
    unallocated_remainder: Decimal
    observed_at: str
    source: str
    mode: str


class InvestmentScenario(BaseModel):
    confirmed_amount: Decimal
    currency: str
    allocations: list[InvestmentAllocation]
    total_allocated: Decimal
    total_remainder: Decimal


class PricedInstrument(BaseModel):
    instrument: CuratedInstrument
    quote: MarketQuote
