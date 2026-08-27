import asyncio
import datetime
import uuid
from decimal import Decimal

import pytest

from app.core.config import settings
from app.features.market_data import service as service_module
from app.features.market_data.schemas import CuratedInstrument, MarketQuote
from app.features.market_data.service import MarketDataService


def _instrument() -> CuratedInstrument:
    return CuratedInstrument(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        code="gold-24k-gram-egp",
        display_name="24K Gold",
        asset_class="gold",
        provider_symbol="XAU_EGP_GRAM_24K",
        price_type="spot",
        price_currency="EGP",
        unit="gram_24k",
        minimum_increment=Decimal("0.01"),
        fractional_units_supported=True,
        max_quote_age_seconds=900,
    )


def _quote(
    instrument: CuratedInstrument,
    *,
    observed_at: datetime.datetime | None = None,
) -> MarketQuote:
    now = datetime.datetime.now(datetime.timezone.utc)
    return MarketQuote(
        instrument_id=instrument.id,
        price=Decimal("4750"),
        price_currency="EGP",
        unit=instrument.unit,
        price_type=instrument.price_type,
        observed_at=observed_at or now,
        received_at=now,
        source="test-provider",
        mode="mock",
    )


@pytest.mark.asyncio
async def test_disabled_fetch_never_constructs_or_calls_provider(monkeypatch):
    instrument = _instrument()
    monkeypatch.setattr(settings.market_data, "enabled", False)

    def fail_if_called():
        raise AssertionError("disabled market data must not construct a provider")

    monkeypatch.setattr(service_module, "get_market_data_service", fail_if_called)

    result = await service_module.fetch_quotes([instrument])

    assert result.quotes == []
    assert result.unavailable == [instrument.id]


@pytest.mark.asyncio
async def test_concurrent_identical_requests_are_coalesced(monkeypatch):
    instrument = _instrument()
    monkeypatch.setattr(settings.market_data, "cache_ttl_seconds", 60)

    class CountingProvider:
        def __init__(self):
            self.calls = 0

        async def get_quotes(self, instruments):
            self.calls += 1
            await asyncio.sleep(0)
            return [_quote(item) for item in instruments]

    provider = CountingProvider()
    service = MarketDataService(provider)

    first, second = await asyncio.gather(
        service.get_quotes([instrument]),
        service.get_quotes([instrument]),
    )

    assert provider.calls == 1
    assert first.quotes[0].price == second.quotes[0].price


@pytest.mark.asyncio
async def test_stale_quote_is_unavailable(monkeypatch):
    instrument = _instrument()
    monkeypatch.setattr(settings.market_data, "cache_ttl_seconds", 60)

    class StaleProvider:
        async def get_quotes(self, instruments):
            observed = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
            return [_quote(instruments[0], observed_at=observed)]

    result = await MarketDataService(StaleProvider()).get_quotes([instrument])

    assert result.quotes == []
    assert result.unavailable == [instrument.id]


@pytest.mark.asyncio
async def test_provider_failure_degrades_to_unavailable(monkeypatch):
    instrument = _instrument()
    monkeypatch.setattr(settings.market_data, "cache_ttl_seconds", 60)

    class FailingProvider:
        async def get_quotes(self, instruments):
            raise TimeoutError("provider timed out")

    result = await MarketDataService(FailingProvider()).get_quotes([instrument])

    assert result.quotes == []
    assert result.unavailable == [instrument.id]
