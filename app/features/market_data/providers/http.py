from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import httpx
from pydantic import BaseModel, Field, field_validator

from app.core.config import MarketDataSettings
from app.features.market_data.schemas import CuratedInstrument, MarketQuote, PriceType


class _HttpQuote(BaseModel):
    instrument_id: uuid.UUID
    price: Decimal = Field(gt=0)
    price_currency: str
    unit: str
    price_type: PriceType
    observed_at: datetime.datetime
    source: str = Field(min_length=1, max_length=120)

    @field_validator("observed_at")
    @classmethod
    def _aware_timestamp(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class _HttpQuoteResponse(BaseModel):
    quotes: list[_HttpQuote] = Field(max_length=50)


class HttpMarketPriceProvider:
    """Adapter for the application-owned normalized ``POST /v1/quotes`` contract."""

    def __init__(
        self,
        config: MarketDataSettings,
        client: httpx.AsyncClient | None = None,
    ):
        self._config = config
        self._client = client

    async def get_quotes(self, instruments: list[CuratedInstrument]) -> list[MarketQuote]:
        headers = {"Accept": "application/json"}
        api_key = self._config.api_key.get_secret_value()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "instruments": [
                {
                    "instrument_id": str(instrument.id),
                    "code": instrument.code,
                    "provider_symbol": instrument.provider_symbol,
                    "asset_class": instrument.asset_class,
                }
                for instrument in instruments
            ]
        }

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            follow_redirects=False,
        )
        try:
            response = await client.post(
                f"{self._config.base_url}/v1/quotes",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            parsed = _HttpQuoteResponse.model_validate(response.json())
        finally:
            if owns_client:
                await client.aclose()

        expected = {instrument.id: instrument for instrument in instruments}
        received_at = datetime.datetime.now(datetime.timezone.utc)
        quotes: list[MarketQuote] = []
        seen: set[uuid.UUID] = set()
        for item in parsed.quotes:
            instrument = expected.get(item.instrument_id)
            if instrument is None or item.instrument_id in seen:
                continue
            if (
                item.price_currency.upper() != instrument.price_currency
                or item.unit != instrument.unit
                or item.price_type != instrument.price_type
            ):
                continue
            seen.add(item.instrument_id)
            quotes.append(
                MarketQuote(
                    instrument_id=item.instrument_id,
                    price=item.price,
                    price_currency=item.price_currency,
                    unit=item.unit,
                    price_type=item.price_type,
                    observed_at=item.observed_at,
                    received_at=received_at,
                    source=item.source,
                    mode="live",
                )
            )
        return quotes
