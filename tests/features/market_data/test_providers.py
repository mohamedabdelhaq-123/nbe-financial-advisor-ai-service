import datetime
import uuid
from decimal import Decimal

import httpx
import pytest

from app.core.config import MarketDataSettings
from app.features.market_data.providers.http import HttpMarketPriceProvider
from app.features.market_data.providers.mock import MockMarketPriceProvider
from app.features.market_data.schemas import CuratedInstrument


def _instrument(**overrides):
    values = dict(
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
    values.update(overrides)
    return CuratedInstrument(**values)


@pytest.mark.asyncio
async def test_mock_provider_preserves_curated_semantics():
    instrument = _instrument()

    quotes = await MockMarketPriceProvider().get_quotes([instrument])

    assert len(quotes) == 1
    assert quotes[0].instrument_id == instrument.id
    assert quotes[0].price == Decimal("4750.00")
    assert quotes[0].unit == "gram_24k"
    assert quotes[0].mode == "mock"


@pytest.mark.asyncio
async def test_http_provider_uses_configured_base_url_and_sends_no_user_data():
    instrument = _instrument()
    observed = datetime.datetime.now(datetime.timezone.utc)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://internal-prices:8090/v1/quotes"
        assert request.headers["authorization"] == "Bearer secret"
        body = __import__("json").loads(request.content)
        assert set(body) == {"instruments"}
        assert set(body["instruments"][0]) == {
            "instrument_id",
            "code",
            "provider_symbol",
            "asset_class",
        }
        return httpx.Response(
            200,
            json={
                "quotes": [
                    {
                        "instrument_id": str(instrument.id),
                        "price": "4800.25",
                        "price_currency": "EGP",
                        "unit": "gram_24k",
                        "price_type": "spot",
                        "observed_at": observed.isoformat(),
                        "source": "internal-market-data",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = MarketDataSettings(
        enabled=True,
        provider="http",
        base_url="http://internal-prices:8090",
        api_key="secret",
    )
    provider = HttpMarketPriceProvider(config, client=client)
    try:
        quotes = await provider.get_quotes([instrument])
    finally:
        await client.aclose()

    assert quotes[0].price == Decimal("4800.25")
    assert quotes[0].mode == "live"


@pytest.mark.asyncio
async def test_http_provider_drops_quote_with_wrong_unit():
    instrument = _instrument()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "quotes": [
                    {
                        "instrument_id": str(instrument.id),
                        "price": "4800.25",
                        "price_currency": "EGP",
                        "unit": "troy_ounce",
                        "price_type": "spot",
                        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "source": "bad-provider",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpMarketPriceProvider(
        MarketDataSettings(
            enabled=True,
            provider="http",
            base_url="https://prices.example",
        ),
        client=client,
    )
    try:
        assert await provider.get_quotes([instrument]) == []
    finally:
        await client.aclose()
