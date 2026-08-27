from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class GatewayInstrument(BaseModel):
    instrument_id: uuid.UUID
    code: str = Field(min_length=1, max_length=120)
    provider_symbol: str = Field(min_length=1, max_length=120)
    asset_class: Literal["gold", "fund", "currency"]


class QuoteRequest(BaseModel):
    instruments: list[GatewayInstrument] = Field(min_length=1, max_length=10)


class GatewayQuote(BaseModel):
    instrument_id: uuid.UUID
    price: Decimal = Field(gt=0)
    price_currency: Literal["EGP"] = "EGP"
    unit: str
    price_type: Literal["spot", "nav", "market_price", "customer_buy_rate"]
    observed_at: datetime.datetime
    source: str


class QuoteResponse(BaseModel):
    quotes: list[GatewayQuote] = Field(default_factory=list)
