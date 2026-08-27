from typing import Protocol

from app.features.market_data.schemas import CuratedInstrument, MarketQuote


class MarketPriceProvider(Protocol):
    async def get_quotes(self, instruments: list[CuratedInstrument]) -> list[MarketQuote]: ...
