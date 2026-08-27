import datetime
from decimal import Decimal

from app.features.market_data.schemas import CuratedInstrument, MarketQuote

_MOCK_PRICES = {
    "gold": Decimal("4750.00"),
    "fund": Decimal("125.50"),
    "currency": Decimal("49.25"),
}


class MockMarketPriceProvider:
    """Deterministic values for Docker development, CI, and demos."""

    async def get_quotes(self, instruments: list[CuratedInstrument]) -> list[MarketQuote]:
        now = datetime.datetime.now(datetime.timezone.utc)
        return [
            MarketQuote(
                instrument_id=instrument.id,
                price=_MOCK_PRICES[instrument.asset_class],
                price_currency=instrument.price_currency,
                unit=instrument.unit,
                price_type=instrument.price_type,
                observed_at=now,
                received_at=now,
                source="mock-market-data",
                mode="mock",
            )
            for instrument in instruments
        ]
