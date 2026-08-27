from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from app.features.investment_plan.schemas import (
    InvestmentAllocation,
    InvestmentScenario,
    PricedInstrument,
)

_MONEY = Decimal("0.01")
_PERCENT = Decimal("0.01")


def _equal_percentages(count: int) -> list[Decimal]:
    if count < 1:
        raise ValueError("At least one instrument is required.")
    base = (Decimal("100") / Decimal(count)).quantize(_PERCENT, rounding=ROUND_DOWN)
    percentages = [base for _ in range(count)]
    percentages[-1] += Decimal("100") - sum(percentages)
    return percentages


def calculate_equal_weight_scenario(
    confirmed_amount: Decimal,
    priced_instruments: list[PricedInstrument],
) -> InvestmentScenario:
    if confirmed_amount <= 0:
        raise ValueError("Confirmed amount must be greater than zero.")
    if not priced_instruments:
        raise ValueError("At least one priced instrument is required.")
    if len({item.instrument.id for item in priced_instruments}) != len(priced_instruments):
        raise ValueError("Instruments must be unique.")

    percentages = _equal_percentages(len(priced_instruments))
    allocations: list[InvestmentAllocation] = []
    for item, percentage in zip(priced_instruments, percentages, strict=True):
        instrument, quote = item.instrument, item.quote
        if quote.instrument_id != instrument.id:
            raise ValueError("Quote does not match its curated instrument.")
        if quote.price_currency != "EGP" or instrument.price_currency != "EGP":
            raise ValueError("The first release supports EGP-priced instruments only.")
        if quote.unit != instrument.unit or quote.price_type != instrument.price_type:
            raise ValueError("Quote semantics do not match the curated instrument.")

        target = (confirmed_amount * percentage / Decimal("100")).quantize(_MONEY)
        increment = instrument.minimum_increment
        raw_units = target / quote.price
        steps = (raw_units / increment).to_integral_value(rounding=ROUND_DOWN)
        quantity = steps * increment
        actual = (quantity * quote.price).quantize(_MONEY)
        remainder = (target - actual).quantize(_MONEY)
        allocations.append(
            InvestmentAllocation(
                instrument_id=instrument.id,
                instrument_code=instrument.code,
                display_name=instrument.display_name,
                asset_class=instrument.asset_class,
                percentage=percentage,
                target_amount=target,
                unit_price=quote.price,
                price_currency=quote.price_currency,
                unit=quote.unit,
                price_type=quote.price_type,
                minimum_increment=increment,
                quantity=quantity,
                actual_allocated_amount=actual,
                unallocated_remainder=remainder,
                observed_at=quote.observed_at.isoformat(),
                source=quote.source,
                mode=quote.mode,
            )
        )

    total_allocated = sum(
        (item.actual_allocated_amount for item in allocations),
        Decimal("0"),
    ).quantize(_MONEY)
    total_remainder = (confirmed_amount - total_allocated).quantize(_MONEY)
    return InvestmentScenario(
        confirmed_amount=confirmed_amount.quantize(_MONEY),
        currency="EGP",
        allocations=allocations,
        total_allocated=total_allocated,
        total_remainder=total_remainder,
    )
