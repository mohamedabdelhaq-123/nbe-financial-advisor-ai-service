"""Deterministic suitability ranking for the curated investment catalogue.

The catalogue owns the suitability metadata. This module only compares that
approved metadata with the questionnaire answers; neither the LLM nor current
prices can invent or change the order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from app.features.market_data.schemas import CuratedInstrument

MatchFactor = Literal["objective", "risk", "horizon", "liquidity", "closest_available"]

_RISK_ORDER = {"low": 0, "moderate": 1, "high": 2}


@dataclass(frozen=True, slots=True)
class RankedInstrument:
    instrument: CuratedInstrument
    priority: int
    score: int
    match_factors: tuple[MatchFactor, ...]


def _risk_score(preference: str | None, instrument_level: str | None) -> tuple[int, bool]:
    if preference not in _RISK_ORDER or instrument_level not in _RISK_ORDER:
        return 0, False
    distance = abs(_RISK_ORDER[preference] - _RISK_ORDER[instrument_level])
    if distance == 0:
        return 3, True
    if distance == 1:
        return 1, False
    return 0, False


def rank_instruments(
    instruments: list[CuratedInstrument],
    answers: Mapping[str, object] | None,
) -> list[RankedInstrument]:
    """Return a stable best-fit order and the exact factors behind it."""

    answers = answers or {}
    objective = str(answers.get("objective") or "")
    risk = str(answers.get("risk") or "")
    horizon = str(answers.get("horizon") or "")
    liquidity = str(answers.get("liquidity") or "")
    scored: list[tuple[int, CuratedInstrument, tuple[MatchFactor, ...]]] = []

    for instrument in instruments:
        score = 0
        factors: list[MatchFactor] = []

        if objective and objective in instrument.objectives:
            score += 4
            factors.append("objective")

        risk_points, exact_risk = _risk_score(risk, instrument.risk_level)
        score += risk_points
        if exact_risk:
            factors.append("risk")

        if horizon and horizon in instrument.horizons:
            score += 2
            factors.append("horizon")

        if liquidity and liquidity == instrument.liquidity_level:
            score += 2
            factors.append("liquidity")

        if not factors:
            factors.append("closest_available")
        scored.append((score, instrument, tuple(factors)))

    scored.sort(key=lambda item: (-item[0], item[1].code))
    return [
        RankedInstrument(
            instrument=instrument,
            priority=index,
            score=score,
            match_factors=factors,
        )
        for index, (score, instrument, factors) in enumerate(scored, start=1)
    ]
