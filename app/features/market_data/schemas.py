from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetClass = Literal["gold", "fund", "currency"]
PriceType = Literal["spot", "nav", "market_price", "customer_buy_rate"]
InvestmentObjective = Literal["preserve_value", "balanced_growth", "income"]
RiskLevel = Literal["low", "moderate", "high"]
InvestmentHorizon = Literal["short", "medium", "long"]
LiquidityLevel = Literal["low", "medium", "high"]


class CuratedInstrument(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    code: str
    display_name: str
    asset_class: AssetClass
    provider_symbol: str
    price_type: PriceType
    price_currency: str
    unit: str
    minimum_increment: Decimal = Field(gt=0)
    fractional_units_supported: bool
    max_quote_age_seconds: int = Field(gt=0)
    aliases: list[str] = Field(default_factory=list)
    objectives: list[InvestmentObjective] = Field(default_factory=list)
    risk_level: RiskLevel | None = None
    horizons: list[InvestmentHorizon] = Field(default_factory=list)
    liquidity_level: LiquidityLevel | None = None

    @field_validator("price_currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.upper()


class MarketQuote(BaseModel):
    instrument_id: uuid.UUID
    price: Decimal = Field(gt=0)
    price_currency: str
    unit: str
    price_type: PriceType
    observed_at: datetime.datetime
    received_at: datetime.datetime
    source: str = Field(min_length=1, max_length=120)
    mode: Literal["live", "mock"]

    @field_validator("price_currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("observed_at", "received_at")
    @classmethod
    def _require_timezone(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Quote timestamps must be timezone-aware.")
        return value


class QuoteBatchResult(BaseModel):
    quotes: list[MarketQuote] = Field(default_factory=list)
    unavailable: list[uuid.UUID] = Field(default_factory=list)
