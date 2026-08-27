import datetime
import uuid
from decimal import Decimal

import httpx
import pytest

from app.market_data_gateway.config import MarketGatewaySettings
from app.market_data_gateway.schemas import GatewayInstrument
from app.market_data_gateway.service import (
    CURRENCY_SYMBOL,
    FUND_SYMBOL,
    GOLD_SYMBOL,
    LiveEgyptMarketDataService,
    parse_fund_market_price,
)


def _instrument(asset_class: str, provider_symbol: str) -> GatewayInstrument:
    return GatewayInstrument(
        instrument_id=uuid.uuid4(),
        code=f"test-{asset_class}",
        provider_symbol=provider_symbol,
        asset_class=asset_class,
    )


def _settings(**overrides) -> MarketGatewaySettings:
    values = {
        "nbe_base_url": "https://nbe.test",
        "gold_base_url": "https://gold.test",
        "fund_base_url": "https://fund.test",
    }
    values.update(overrides)
    return MarketGatewaySettings(**values)


def _nbe_response() -> dict:
    return {
        "ResultCode": "0",
        "RspObj": {
            "Item": {
                "Body": {
                    "ExchangeRateGetRatesRspParams": {
                        "Currencies": [
                            {
                                "CurrencyISOCode": "USD",
                                "CashBuyRate": "50.17",
                                "CashSellRate": "50.27",
                            }
                        ],
                        "LastUpdateDateUSD_EN": "26 August 2026 17:46:48",
                    }
                }
            }
        },
    }


FUND_HTML = """
<h1>EGX 30 Index ETF (EGX30ETF)</h1>
<div class="market-summary">
  <div class="market-summary__date">Last update: 01:14 PM market time.</div>
  <div class="market-summary__last-price">63.40</div>
  <div class="market-summary__note">All data are 15 minutes late during market session</div>
</div>
"""


@pytest.mark.asyncio
async def test_live_gateway_normalizes_all_three_supported_sources():
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.url.host == "nbe.test" and request.method == "GET":
            return httpx.Response(200, headers={"set-cookie": "waf=ok; Path=/"})
        if request.url.host == "nbe.test":
            assert request.headers["x-xsrf"]
            assert "I_InputObjectJSONStr=" in request.content.decode()
            return httpx.Response(200, json=_nbe_response())
        if request.url.host == "gold.test":
            return httpx.Response(
                200,
                json={
                    "currency": "USD",
                    "price": 4595.2,
                    "symbol": "XAU",
                    "updatedAt": "2026-08-26T18:22:44Z",
                },
            )
        return httpx.Response(
            200,
            text=FUND_HTML,
            headers={"Date": "Wed, 26 Aug 2026 10:30:00 GMT"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = LiveEgyptMarketDataService(_settings(), client=client)
    instruments = [
        _instrument("gold", GOLD_SYMBOL),
        _instrument("fund", FUND_SYMBOL),
        _instrument("currency", CURRENCY_SYMBOL),
    ]
    try:
        quotes = await service.get_quotes(instruments)
    finally:
        await client.aclose()

    assert [quote.instrument_id for quote in quotes] == [item.instrument_id for item in instruments]
    assert quotes[0].price == Decimal("7426.8451")
    assert quotes[0].unit == "gram_24k"
    assert quotes[0].price_type == "spot"
    assert quotes[1].price == Decimal("63.40")
    assert quotes[1].price_type == "market_price"
    assert quotes[1].observed_at.utcoffset() == datetime.timedelta(hours=3)
    assert quotes[2].price_type == "customer_buy_rate"
    assert quotes[2].price == Decimal("50.27")
    assert "cash-sell" in quotes[2].source
    assert any(method == "POST" and "TrackID=" in url for method, url in calls)


@pytest.mark.asyncio
async def test_one_source_failure_does_not_fabricate_or_redistribute_quotes():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nbe.test" and request.method == "GET":
            return httpx.Response(200)
        if request.url.host == "nbe.test":
            return httpx.Response(200, json=_nbe_response())
        if request.url.host == "gold.test":
            return httpx.Response(503)
        return httpx.Response(
            200,
            text=FUND_HTML,
            headers={"Date": "Wed, 26 Aug 2026 10:30:00 GMT"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = LiveEgyptMarketDataService(_settings(), client=client)
    instruments = [
        _instrument("gold", GOLD_SYMBOL),
        _instrument("fund", FUND_SYMBOL),
        _instrument("currency", CURRENCY_SYMBOL),
    ]
    try:
        quotes = await service.get_quotes(instruments)
    finally:
        await client.aclose()

    assert [quote.instrument_id for quote in quotes] == [
        instruments[1].instrument_id,
        instruments[2].instrument_id,
    ]


@pytest.mark.asyncio
async def test_unknown_or_mismatched_instrument_is_not_quoted():
    async def unexpected_call(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected outbound call: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(unexpected_call))
    service = LiveEgyptMarketDataService(_settings(), client=client)
    try:
        quotes = await service.get_quotes([_instrument("fund", GOLD_SYMBOL)])
    finally:
        await client.aclose()

    assert quotes == []


def test_fund_parser_uses_identified_market_price_and_market_time():
    quote = parse_fund_market_price(
        FUND_HTML,
        datetime.datetime(2026, 8, 26, 10, 30, tzinfo=datetime.timezone.utc),
    )

    assert quote.price_per_unit == Decimal("63.40")
    assert quote.observed_at.date() == datetime.date(2026, 8, 26)
    assert quote.observed_at.time() == datetime.time(13, 14)


def test_fund_parser_moves_weekend_timestamp_to_last_egx_trading_day():
    quote = parse_fund_market_price(
        FUND_HTML,
        datetime.datetime(2026, 8, 28, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert quote.observed_at.date() == datetime.date(2026, 8, 27)


@pytest.mark.asyncio
async def test_gateway_requires_all_source_base_urls_when_called():
    service = LiveEgyptMarketDataService(MarketGatewaySettings())

    with pytest.raises(RuntimeError, match="MARKET_GATEWAY_NBE_BASE_URL"):
        await service.get_quotes([_instrument("gold", GOLD_SYMBOL)])
