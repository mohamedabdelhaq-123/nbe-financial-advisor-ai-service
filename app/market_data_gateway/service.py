from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.market_data_gateway.config import MarketGatewaySettings
from app.market_data_gateway.schemas import GatewayInstrument, GatewayQuote

TROY_OUNCE_GRAMS = Decimal("31.1034768")
CAIRO = ZoneInfo("Africa/Cairo")

GOLD_SYMBOL = "XAU_EGP_GRAM_24K"
FUND_SYMBOL = "EGX30ETF_MARKET_PRICE"
CURRENCY_SYMBOL = "USD_EGP_BUY"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NbeUsdRate:
    cash_buy: Decimal
    cash_sell: Decimal
    observed_at: datetime.datetime


@dataclass(frozen=True)
class GoldUsdQuote:
    price_per_troy_ounce: Decimal
    observed_at: datetime.datetime


@dataclass(frozen=True)
class FundMarketPrice:
    price_per_unit: Decimal
    observed_at: datetime.datetime


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _parse_nbe_timestamp(value: str) -> datetime.datetime:
    parsed = datetime.datetime.strptime(value.strip(), "%d %B %Y %H:%M:%S")
    return parsed.replace(tzinfo=CAIRO)


def parse_nbe_usd_rate(payload: dict[str, Any]) -> NbeUsdRate:
    if str(payload.get("ResultCode")) != "0":
        raise ValueError("NBE exchange response reported failure")
    body = payload["RspObj"]["Item"]["Body"]["ExchangeRateGetRatesRspParams"]
    usd = next(item for item in body["Currencies"] if item.get("CurrencyISOCode") == "USD")
    return NbeUsdRate(
        cash_buy=_positive_decimal(usd.get("CashBuyRate"), "NBE USD cash buy rate"),
        cash_sell=_positive_decimal(usd.get("CashSellRate"), "NBE USD cash sell rate"),
        observed_at=_parse_nbe_timestamp(body["LastUpdateDateUSD_EN"]),
    )


def parse_gold_usd_quote(payload: dict[str, Any]) -> GoldUsdQuote:
    if payload.get("symbol") != "XAU" or payload.get("currency") != "USD":
        raise ValueError("Gold response has unexpected symbol or currency")
    observed_at = datetime.datetime.fromisoformat(str(payload["updatedAt"]).replace("Z", "+00:00"))
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Gold response timestamp must include a timezone")
    return GoldUsdQuote(
        price_per_troy_ounce=_positive_decimal(payload.get("price"), "gold price"),
        observed_at=observed_at,
    )


def _latest_egx_trading_datetime(
    market_time: datetime.time,
    retrieved_at: datetime.datetime,
) -> datetime.datetime:
    """Attach a date to Mubasher's time-only quote timestamp.

    EGX trades Sunday through Thursday. The page does not include the date in
    its quote header, so use retrieval time and move backwards across future
    times and the Friday/Saturday weekend.
    """

    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("fund retrieval timestamp must include a timezone")
    cairo_retrieved_at = retrieved_at.astimezone(CAIRO)
    observed_at = datetime.datetime.combine(cairo_retrieved_at.date(), market_time, tzinfo=CAIRO)
    if observed_at > cairo_retrieved_at + datetime.timedelta(minutes=5):
        observed_at -= datetime.timedelta(days=1)
    while observed_at.weekday() in {4, 5}:  # Friday and Saturday
        observed_at -= datetime.timedelta(days=1)
    return observed_at


def parse_fund_market_price(
    html: str,
    retrieved_at: datetime.datetime | None = None,
) -> FundMarketPrice:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    if heading is None or "EGX30ETF" not in heading.get_text(" ", strip=True).upper():
        raise ValueError("fund page does not identify the requested EGX30 ETF")
    price_node = soup.select_one(".market-summary__last-price")
    timestamp_node = soup.select_one(".market-summary__date")
    if price_node is None or timestamp_node is None:
        raise ValueError("fund page market price or update time is missing")
    timestamp_text = " ".join(timestamp_node.get_text(" ", strip=True).split())
    time_match = re.search(r"(\d{1,2}:\d{2})\s*([AP]M)", timestamp_text, re.IGNORECASE)
    if time_match is None:
        raise ValueError("fund page update time is not recognized")
    market_time = datetime.datetime.strptime(
        f"{time_match.group(1)} {time_match.group(2).upper()}", "%I:%M %p"
    ).time()
    retrieved_at = retrieved_at or datetime.datetime.now(datetime.timezone.utc)
    return FundMarketPrice(
        price_per_unit=_positive_decimal(price_node.get_text(strip=True), "fund market price"),
        observed_at=_latest_egx_trading_datetime(market_time, retrieved_at),
    )


def _nbe_exchange_payload(now: datetime.datetime, request_id: str) -> dict[str, Any]:
    cairo_now = now.astimezone(CAIRO)
    return {
        "__type": "eChannelManagerBusinessXML.eBank",
        "Item": {
            "__type": "eChannelManagerBusinessXML.schExchangeRateGetRates",
            "Body": {
                "__type": "eChannelManagerBusinessXML.schExchangeRateGetRatesBody",
                "ExchangeRateGetRatesReqParams": {
                    "__type": (
                        "eChannelManagerBusinessXML."
                        "schExchangeRateGetRatesBodyExchangeRateGetRatesReqParams"
                    ),
                    "HighLightCurrency": False,
                    "RequestType": "ExchangeRates",
                },
            },
            "Header": {
                "__type": "eChannelManagerBusinessXML.Header",
                "Customer": {
                    "__type": "eChannelManagerBusinessXML.CustomerHeaderInfoType",
                    "CustomerID": "",
                    "CustomerPin": "",
                    "CustDeviceID": "",
                    "CustLoginIDOnChannel": "_",
                },
                "FrontEnd": {
                    "FrontEndID": "eCM-Web",
                    "FrontEndType": "eCM-Web",
                    "FrontEndPassword": "",
                },
                "Audit": {
                    "__type": "eChannelManagerBusinessXML.AuditHeaderInfoType",
                    "TransactionObj": {
                        "__type": "eChannelManagerBusinessXML.TransactionObjType",
                        "MasterLogLevel": "",
                        "TransactionID": request_id,
                        "TransactionPath": "ExchangeRateGetRates",
                        "TransactionType": "ExchangeRateGetRates",
                        "TransCustID": cairo_now.strftime("%Y-%m-%dT%H:%M:%S"),
                        "TransFrontEndID": "eCM-Mobile",
                        "TransFrontEndType": "eCM-Web",
                    },
                    "SessionObj": {
                        "__type": "eChannelManagerBusinessXML.SessionObjType",
                        "SessionObjID": "Session_",
                    },
                },
                "User": {
                    "__type": "eChannelManagerBusinessXML.UserHeaderInfoType",
                    "UserID": "",
                    "UserPin": "",
                },
                "MemoList": {
                    "MemoItem1": "",
                    "MemoItem2": "false",
                    "MemoItem6": "",
                    "MemoItem7": "",
                    "MemoItem8": "",
                },
                "Service": {
                    "__type": "eChannelManagerBusinessXML.ServiceHeaderInfoType",
                    "ServiceID": "ExchangeRateGetRates",
                    "ServiceMessageType": "ExchangeRateGetRates",
                    "ServiceRequestID": request_id,
                    "ServiceRequestLanguageCode": "EN",
                    "ServiceRequestTime": now.isoformat(timespec="milliseconds").replace(
                        "+00:00", "Z"
                    ),
                    "ServiceRequestTimeSpecified": True,
                    "ServiceResult": {
                        "__type": "eChannelManagerBusinessXML.ResultHeaderInfoType",
                        "ResultCode": "0",
                        "ResultDesc": "",
                    },
                },
                "CachingAndExpiryControl": {
                    "__type": "eChannelManagerBusinessXML.HeaderCachingAndExpiryControl",
                    "DataHashSignature": "",
                },
            },
        },
    }


class LiveEgyptMarketDataService:
    """Normalizes the configured public sources into the application's quote schema."""

    def __init__(
        self,
        settings: MarketGatewaySettings,
        client: httpx.AsyncClient | None = None,
    ):
        self._settings = settings
        self._client = client

    async def _fetch_nbe_usd_rate(self, client: httpx.AsyncClient) -> NbeUsdRate:
        landing_response = await client.get(_url(self._settings.nbe_base_url, "/NBE/E/"))
        landing_response.raise_for_status()
        xsrf = str(uuid.uuid4())
        host = httpx.URL(self._settings.nbe_base_url).host
        if host is None:
            raise ValueError("NBE base URL has no host")
        client.cookies.set("X-XSRF", xsrf, domain=host, path="/")
        now = datetime.datetime.now(datetime.timezone.utc)
        request_id = str(uuid.uuid4())
        response = await client.post(
            _url(self._settings.nbe_base_url, self._settings.nbe_exchange_path),
            params={"TrackID": str(uuid.uuid4())},
            data={
                "I_InputObjectJSONStr": json.dumps(
                    _nbe_exchange_payload(now, request_id), separators=(",", ":")
                ),
                "AJAXReqDate": str(int(time.time() * 1000)),
            },
            headers={
                "Accept": "*/*",
                "Origin": self._settings.nbe_base_url,
                "Referer": f"{self._settings.nbe_base_url}/NBE/E/",
                "X-XSRF": xsrf,
            },
        )
        response.raise_for_status()
        return parse_nbe_usd_rate(response.json())

    async def _fetch_gold_usd(self, client: httpx.AsyncClient) -> GoldUsdQuote:
        response = await client.get(
            _url(self._settings.gold_base_url, self._settings.gold_quote_path)
        )
        response.raise_for_status()
        return parse_gold_usd_quote(response.json())

    async def _fetch_fund_market_price(self, client: httpx.AsyncClient) -> FundMarketPrice:
        response = await client.get(
            _url(self._settings.fund_base_url, self._settings.fund_quote_path)
        )
        response.raise_for_status()
        retrieved_at = None
        if response.headers.get("Date"):
            retrieved_at = parsedate_to_datetime(response.headers["Date"])
        return parse_fund_market_price(response.text, retrieved_at)

    async def get_quotes(self, instruments: list[GatewayInstrument]) -> list[GatewayQuote]:
        self._settings.require_configured()
        requested_symbols = {item.provider_symbol for item in instruments}
        needs_nbe = bool(requested_symbols & {GOLD_SYMBOL, CURRENCY_SYMBOL})
        needs_gold = GOLD_SYMBOL in requested_symbols
        needs_fund = FUND_SYMBOL in requested_symbols

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "NBE-Financial-Advisor-Market-Gateway/1.0"},
        )
        try:
            task_names: list[str] = []
            tasks: list[Any] = []
            if needs_nbe:
                task_names.append("nbe")
                tasks.append(self._fetch_nbe_usd_rate(client))
            if needs_gold:
                task_names.append("gold")
                tasks.append(self._fetch_gold_usd(client))
            if needs_fund:
                task_names.append("fund")
                tasks.append(self._fetch_fund_market_price(client))
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if owns_client:
                await client.aclose()

        fetched = dict(zip(task_names, results, strict=True))
        for source_name, result in fetched.items():
            if isinstance(result, BaseException):
                logger.warning(
                    "market source unavailable: %s (%s)",
                    source_name,
                    type(result).__name__,
                )
        nbe = fetched.get("nbe")
        gold = fetched.get("gold")
        fund = fetched.get("fund")
        quotes: list[GatewayQuote] = []
        for instrument in instruments:
            if (
                instrument.provider_symbol == GOLD_SYMBOL
                and instrument.asset_class == "gold"
                and isinstance(nbe, NbeUsdRate)
                and isinstance(gold, GoldUsdQuote)
            ):
                price = (gold.price_per_troy_ounce * nbe.cash_sell / TROY_OUNCE_GRAMS).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                quotes.append(
                    GatewayQuote(
                        instrument_id=instrument.instrument_id,
                        price=price,
                        unit="gram_24k",
                        price_type="spot",
                        observed_at=gold.observed_at,
                        source="gold-api.com XAU/USD + NBE USD cash-sell rate",
                    )
                )
            elif (
                instrument.provider_symbol == FUND_SYMBOL
                and instrument.asset_class == "fund"
                and isinstance(fund, FundMarketPrice)
            ):
                quotes.append(
                    GatewayQuote(
                        instrument_id=instrument.instrument_id,
                        price=fund.price_per_unit,
                        unit="fund_unit",
                        price_type="market_price",
                        observed_at=fund.observed_at,
                        source="Mubasher delayed EGX market price",
                    )
                )
            elif (
                instrument.provider_symbol == CURRENCY_SYMBOL
                and instrument.asset_class == "currency"
                and isinstance(nbe, NbeUsdRate)
            ):
                quotes.append(
                    GatewayQuote(
                        instrument_id=instrument.instrument_id,
                        # NBE publishes rates from the bank's perspective. A
                        # customer spending EGP to buy USD pays the bank's
                        # cash-sell rate, which is the application's
                        # customer_buy_rate semantic.
                        price=nbe.cash_sell,
                        unit="USD",
                        price_type="customer_buy_rate",
                        observed_at=nbe.observed_at,
                        source="NBE cash-sell rate (customer buys USD)",
                    )
                )
        return quotes
