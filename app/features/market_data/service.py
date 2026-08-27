from __future__ import annotations

import asyncio
import datetime
import time
import uuid
from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from app.features.market_data.providers import HttpMarketPriceProvider, MockMarketPriceProvider
from app.features.market_data.providers.base import MarketPriceProvider
from app.features.market_data.schemas import CuratedInstrument, MarketQuote, QuoteBatchResult

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_market_price_provider() -> MarketPriceProvider:
    if settings.market_data.provider == "http":
        return HttpMarketPriceProvider(settings.market_data)
    return MockMarketPriceProvider()


class MarketDataService:
    def __init__(self, provider: MarketPriceProvider):
        self._provider = provider
        self._cache: dict[uuid.UUID, tuple[float, MarketQuote]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _fresh_for_instrument(quote: MarketQuote, instrument: CuratedInstrument) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        age = (now - quote.observed_at.astimezone(datetime.timezone.utc)).total_seconds()
        return -300 <= age <= instrument.max_quote_age_seconds

    async def get_quotes(self, instruments: list[CuratedInstrument]) -> QuoteBatchResult:
        if not instruments:
            return QuoteBatchResult()

        now_mono = time.monotonic()
        found: dict[uuid.UUID, MarketQuote] = {}
        missing: list[CuratedInstrument] = []
        for instrument in instruments:
            cached = self._cache.get(instrument.id)
            if (
                cached is not None
                and cached[0] >= now_mono
                and self._fresh_for_instrument(cached[1], instrument)
            ):
                found[instrument.id] = cached[1]
            else:
                missing.append(instrument)

        if missing:
            async with self._lock:
                # A concurrent request may have populated the cache while this
                # request waited for the lock. Recheck before calling the
                # provider so identical batches collapse into one outbound call.
                now_mono = time.monotonic()
                still_missing: list[CuratedInstrument] = []
                for instrument in missing:
                    cached = self._cache.get(instrument.id)
                    if (
                        cached is not None
                        and cached[0] >= now_mono
                        and self._fresh_for_instrument(cached[1], instrument)
                    ):
                        found[instrument.id] = cached[1]
                    else:
                        still_missing.append(instrument)
                try:
                    returned = (
                        await self._provider.get_quotes(still_missing) if still_missing else []
                    )
                except Exception:
                    logger.exception(
                        "market_data_provider_failed",
                        provider=settings.market_data.provider,
                        instrument_count=len(still_missing),
                    )
                    returned = []
                missing_by_id = {item.id: item for item in still_missing}
                for quote in returned:
                    matched_instrument = missing_by_id.get(quote.instrument_id)
                    if matched_instrument is None or not self._fresh_for_instrument(
                        quote, matched_instrument
                    ):
                        continue
                    found[quote.instrument_id] = quote
                    if settings.market_data.cache_ttl_seconds > 0:
                        self._cache[quote.instrument_id] = (
                            time.monotonic() + settings.market_data.cache_ttl_seconds,
                            quote,
                        )

        ordered_quotes = [found[item.id] for item in instruments if item.id in found]
        unavailable = [item.id for item in instruments if item.id not in found]
        return QuoteBatchResult(quotes=ordered_quotes, unavailable=unavailable)


@lru_cache(maxsize=1)
def get_market_data_service() -> MarketDataService:
    return MarketDataService(get_market_price_provider())


async def fetch_quotes(instruments: list[CuratedInstrument]) -> QuoteBatchResult:
    if not settings.market_data.enabled:
        return QuoteBatchResult(unavailable=[item.id for item in instruments])
    return await get_market_data_service().get_quotes(instruments)
