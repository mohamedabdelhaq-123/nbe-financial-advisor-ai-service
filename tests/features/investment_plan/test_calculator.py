import datetime
import uuid
from decimal import Decimal

import pytest

from app.features.investment_plan.calculator import calculate_equal_weight_scenario
from app.features.investment_plan.schemas import PricedInstrument
from app.features.market_data.schemas import CuratedInstrument, MarketQuote


def _priced(asset_class, price, increment, unit, price_type):
    instrument_id = uuid.uuid4()
    instrument = CuratedInstrument(
        id=instrument_id,
        product_id=uuid.uuid4(),
        code=f"{asset_class}-instrument",
        display_name=f"{asset_class.title()} instrument",
        asset_class=asset_class,
        provider_symbol=f"{asset_class.upper()}_SYMBOL",
        price_type=price_type,
        price_currency="EGP",
        unit=unit,
        minimum_increment=Decimal(increment),
        fractional_units_supported=Decimal(increment) < 1,
        max_quote_age_seconds=3600,
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    quote = MarketQuote(
        instrument_id=instrument_id,
        price=Decimal(price),
        price_currency="EGP",
        unit=unit,
        price_type=price_type,
        observed_at=now,
        received_at=now,
        source="test",
        mode="mock",
    )
    return PricedInstrument(instrument=instrument, quote=quote)


def test_equal_weight_calculation_uses_decimal_and_purchase_increment():
    priced = [
        _priced("gold", "4750", "0.01", "gram_24k", "spot"),
        _priced("fund", "125.50", "1", "fund_unit", "nav"),
        _priced("currency", "49.25", "1", "USD", "customer_buy_rate"),
    ]

    scenario = calculate_equal_weight_scenario(Decimal("10000"), priced)

    assert [item.percentage for item in scenario.allocations] == [
        Decimal("33.33"),
        Decimal("33.33"),
        Decimal("33.34"),
    ]
    assert scenario.allocations[0].quantity == Decimal("0.70")
    assert scenario.allocations[1].quantity == Decimal("26")
    assert scenario.total_allocated + scenario.total_remainder == Decimal("10000.00")


def test_calculator_rejects_non_egp_quote():
    priced = _priced("gold", "100", "0.01", "gram_24k", "spot")
    priced.quote.price_currency = "USD"

    with pytest.raises(ValueError, match="EGP-priced"):
        calculate_equal_weight_scenario(Decimal("1000"), [priced])


def test_calculator_rejects_duplicate_instrument():
    priced = _priced("fund", "100", "1", "fund_unit", "nav")
    with pytest.raises(ValueError, match="unique"):
        calculate_equal_weight_scenario(Decimal("1000"), [priced, priced])
