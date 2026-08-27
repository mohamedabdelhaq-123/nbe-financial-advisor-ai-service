from __future__ import annotations

import uuid
from typing import TypeVar, cast

from sqlalchemy import select

from app.backend_db.models import InvestmentInstrument, Product
from app.features.market_data.schemas import (
    CuratedInstrument,
    InvestmentHorizon,
    InvestmentObjective,
    LiquidityLevel,
    RiskLevel,
)

_OBJECTIVES: set[InvestmentObjective] = {"preserve_value", "balanced_growth", "income"}
_RISK_LEVELS: set[RiskLevel] = {"low", "moderate", "high"}
_HORIZONS: set[InvestmentHorizon] = {"short", "medium", "long"}
_LIQUIDITY_LEVELS: set[LiquidityLevel] = {"low", "medium", "high"}
_AllowedValue = TypeVar("_AllowedValue", bound=str)


def _allowed_list(value: object, allowed: set[_AllowedValue]) -> list[_AllowedValue]:
    if not isinstance(value, list):
        return []
    return [
        cast(_AllowedValue, item) for item in value if isinstance(item, str) and item in allowed
    ]


def _aliases(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _allowed_value(value: object, allowed: set[_AllowedValue]) -> _AllowedValue | None:
    return cast(_AllowedValue, value) if isinstance(value, str) and value in allowed else None


async def list_curated_instruments(
    instrument_ids: list[uuid.UUID] | None = None,
) -> list[CuratedInstrument]:
    """Return active, product-approved instruments through the read-only DB role."""

    stmt = (
        select(InvestmentInstrument, Product)
        .join(Product, Product.id == InvestmentInstrument.product_id)
        .where(InvestmentInstrument.is_active.is_(True), Product.is_active.is_(True))
        .order_by(InvestmentInstrument.code)
    )
    if instrument_ids is not None:
        stmt = stmt.where(InvestmentInstrument.id.in_(instrument_ids))

    from app.backend_db import get_backend_session

    instruments: list[CuratedInstrument] = []
    async for session in get_backend_session():
        result = await session.execute(stmt)
        instruments = []
        for instrument, product in result.all():
            features = product.features or {}
            instruments.append(
                CuratedInstrument(
                    id=instrument.id,
                    product_id=instrument.product_id,
                    code=instrument.code,
                    display_name=product.title,
                    asset_class=instrument.asset_class,
                    provider_symbol=instrument.provider_symbol,
                    price_type=instrument.price_type,
                    price_currency=instrument.price_currency,
                    unit=instrument.unit,
                    minimum_increment=instrument.minimum_increment,
                    fractional_units_supported=instrument.fractional_units_supported,
                    max_quote_age_seconds=instrument.max_quote_age_seconds,
                    aliases=_aliases(features.get("investment_aliases")),
                    objectives=_allowed_list(features.get("investment_objectives"), _OBJECTIVES),
                    risk_level=_allowed_value(features.get("risk_level"), _RISK_LEVELS),
                    horizons=_allowed_list(features.get("investment_horizons"), _HORIZONS),
                    liquidity_level=_allowed_value(features.get("liquidity"), _LIQUIDITY_LEVELS),
                )
            )
    if instrument_ids is None:
        return instruments
    by_id = {instrument.id: instrument for instrument in instruments}
    return [by_id[item] for item in instrument_ids if item in by_id]
