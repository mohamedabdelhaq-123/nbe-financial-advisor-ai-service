"""Interrupt-based investment planning over curated, optionally priced instruments."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from app.core.config import settings
from app.features.chat.guards import with_disclaimer
from app.features.chat.schemas import (
    InvestmentPlanAllocationPayload,
    InvestmentPlanPayload,
    InvestmentPlanWidget,
)
from app.features.chat.state import ConversationState
from app.features.investment_plan.calculator import calculate_equal_weight_scenario
from app.features.investment_plan.ranking import RankedInstrument, rank_instruments
from app.features.investment_plan.schemas import InvestmentContext, PricedInstrument
from app.features.market_data.service import fetch_quotes

MAX_VALIDATION_ATTEMPTS = 3
MAX_CONFIRMED_AMOUNT = Decimal("1000000000")
_AMOUNT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩٫٬",
    "0123456789.,",
)
_AMOUNT_PATTERN = re.compile(r"(?<![\d.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.,kKmM])")
_UNIT_LABELS = {
    "gram_24k": "gram of 24K gold",
    "fund_unit": "fund unit",
    "USD": "USD",
}
_ALL_SELECTIONS = {"all", "all three", "everything", "الكل", "كلهم", "جميعهم"}
_CHOICE_ALIASES = {
    "objective": {
        "preserve_value": {
            "preserve value",
            "preserve",
            "protect value",
            "protect",
            "safety",
            "safe",
            "حفظ القيمة",
            "حماية",
        },
        "balanced_growth": {
            "balanced growth",
            "steady growth",
            "growth",
            "grow",
            "balanced",
            "نمو",
        },
        "income": {"income", "regular income", "cash flow", "دخل"},
    },
    "risk": {
        "low": {"low", "conservative", "cautious"},
        "moderate": {"moderate", "medium", "balanced"},
        "high": {"high", "aggressive"},
    },
    "horizon": {
        "short": {"short", "short term", "under a year", "less than a year"},
        "medium": {"medium", "medium term", "one to three years", "1 to 3 years"},
        "long": {"long", "long term", "over three years", "more than three years"},
    },
    "liquidity": {
        "high": {"high", "quick", "quickly", "immediate", "very important"},
        "medium": {"medium", "moderate", "some flexibility"},
        "low": {"low", "not important", "not soon", "can wait"},
    },
}
_QUESTION_ORDER = (
    "confirmed_amount",
    "objective",
    "risk",
    "horizon",
    "liquidity",
    "instruments",
)


def _match_reason_text(ranked: RankedInstrument, answers: dict) -> str:
    objective = str(answers.get("objective", "")).replace("_", " ")
    phrases = {
        "objective": f"your {objective} goal",
        "risk": f"{answers.get('risk', '')} risk",
        "horizon": f"a {answers.get('horizon', '')}-term horizon",
        "liquidity": f"{answers.get('liquidity', '')} liquidity",
        "closest_available": "a lower fit for your current preferences",
    }
    return " and ".join(phrases[factor] for factor in ranked.match_factors[:2])


def _selection_options_text(ranked: list[RankedInstrument], answers: dict) -> str:
    return "\n\n".join(
        f"**Priority {item.priority} — {item.instrument.display_name}**\n"
        f"Why: {_match_reason_text(item, answers)}"
        for item in ranked
    )


def _money_display(value: Decimal | None) -> str:
    return "not available" if value is None else f"{value:,.0f}"


def _question_text(
    question_id: str,
    context: InvestmentContext,
    reason: str | None,
    answers: dict | None = None,
) -> str:
    if question_id == "confirmed_amount":
        if reason:
            return f"{reason}\n\nTry one amount, such as **1,200 EGP**."
        if context.estimated_monthly_surplus is None:
            return (
                "I could not estimate money left from your recent data.\n\n"
                "How much would you like to plan with? For example: **1,200 EGP**."
            )
        return (
            f"Based on your last {context.months_used} complete months, you may have about "
            f"**{_money_display(context.estimated_monthly_surplus)} {context.currency} left "
            "each month**.\n\n"
            f"Income {_money_display(context.average_monthly_income)} − spending "
            f"{_money_display(context.average_monthly_expenses)} − goals "
            f"{_money_display(context.monthly_goal_commitment)}.\n\n"
            "This is an estimate, not your account balance. How much should we use for this plan?"
        )
    if question_id == "risk":
        if reason:
            return f"{reason}\n\nTry **low**, **moderate**, or **high**."
        return (
            "How much price movement are you comfortable with: "
            "**low**, **moderate**, or **high**?"
        )
    if question_id == "objective":
        if reason:
            return f"{reason}\n\nTry **protect**, **growth**, or **income**."
        return (
            "What should this money do for you: **protect its value**, "
            "**grow**, or **provide income**?"
        )
    if question_id == "horizon":
        if reason:
            return f"{reason}\n\nTry **short**, **medium**, or **long**."
        return "When might you need this money: **short**, **medium**, or **long** term?"
    if question_id == "liquidity":
        if reason:
            return f"{reason}\n\nTry **quickly**, **some flexibility**, or **not soon**."
        return (
            "How quickly might you need access: **quickly**, "
            "**some flexibility**, or **not soon**?"
        )

    ranked = rank_instruments(context.instruments[: settings.market_data.max_batch_size], answers)
    choices = _selection_options_text(ranked, answers or {})
    if reason:
        return f"{reason}\n\n{choices}\n\n" "Reply with up to three priority numbers or names."
    return (
        "Here is your suggested priority order:\n\n"
        f"{choices}\n\n"
        "This is based on your preferences, not predicted returns. Which should we use? "
        "Reply with up to three priority numbers or names."
    )


def _normalize_instrument_alias(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^\w\s]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.removeprefix("the ").strip()


def _alias_occurs(text: str, alias: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text))


def _parse_natural_choice(question_id: str, cleaned: str) -> str | None:
    normalized = _normalize_instrument_alias(cleaned)
    matches: set[str] = set()
    for canonical, phrases in _CHOICE_ALIASES[question_id].items():
        for phrase in sorted(phrases, key=len, reverse=True):
            normalized_phrase = _normalize_instrument_alias(phrase)
            if normalized == normalized_phrase or _alias_occurs(normalized, normalized_phrase):
                matches.add(canonical)
                break
    return matches.pop() if len(matches) == 1 else None


def _parse_answer(
    question_id: str,
    raw: str,
    context: InvestmentContext,
    answers: dict | None = None,
):
    cleaned = raw.strip()
    if question_id == "confirmed_amount":
        normalized_amount = cleaned.translate(_AMOUNT_TRANSLATION)
        matches = _AMOUNT_PATTERN.findall(normalized_amount)
        if len(matches) != 1:
            return None, "Please provide one unambiguous numeric EGP amount."
        try:
            amount = Decimal(matches[0].replace(",", ""))
        except InvalidOperation:
            return None, "Please enter a numeric EGP amount."
        if amount <= 0:
            return None, "The confirmed amount must be greater than zero."
        if amount > MAX_CONFIRMED_AMOUNT:
            return None, "The confirmed amount must not exceed 1,000,000,000 EGP."
        return str(amount.quantize(Decimal("0.01"))), None

    if question_id == "objective":
        parsed = _parse_natural_choice(question_id, cleaned)
        return (parsed, None) if parsed else (None, "I didn't understand the goal.")

    if question_id in {"risk", "liquidity"}:
        parsed = _parse_natural_choice(question_id, cleaned)
        return (parsed, None) if parsed else (None, "I didn't understand that preference.")

    if question_id == "horizon":
        parsed = _parse_natural_choice(question_id, cleaned)
        return (parsed, None) if parsed else (None, "I didn't understand the time frame.")

    if not context.instruments:
        return None, "No curated investment opportunities are currently available."
    ranked = rank_instruments(context.instruments[: settings.market_data.max_batch_size], answers)
    if _normalize_instrument_alias(cleaned) in _ALL_SELECTIONS:
        selected = [item.instrument for item in ranked]
    else:
        choices: dict[str, list] = {}
        for ranked_item in ranked:
            item = ranked_item.instrument
            for alias in {item.code, item.display_name, *item.aliases}:
                normalized_alias = _normalize_instrument_alias(alias)
                bucket = choices.setdefault(normalized_alias, [])
                if item.id not in {existing.id for existing in bucket}:
                    bucket.append(item)

        selected = []
        normalized = _normalize_instrument_alias(cleaned)
        numeric_selection = re.fullmatch(
            r"\d+\s*(?:(?:,|،|;|\band\b)\s*\d+\s*)*",
            normalized,
        )
        if numeric_selection:
            for number in re.findall(r"\d+", normalized):
                priority = int(number)
                if not 1 <= priority <= len(ranked):
                    return None, f"Priority {priority} is not available."
                item = ranked[priority - 1].instrument
                if item.id not in {existing.id for existing in selected}:
                    selected.append(item)
        else:
            matched_ids: set = set()
            for alias in sorted(choices, key=len, reverse=True):
                if not alias or not _alias_occurs(normalized, alias):
                    continue
                matches = choices[alias]
                if len(matches) != 1:
                    return None, f"'{alias}' matches more than one option."
                matched_ids.add(matches[0].id)
            selected = [item.instrument for item in ranked if item.instrument.id in matched_ids]
            if not selected:
                prefix_ids: set = set()
                for word in (word for word in normalized.split() if len(word) >= 3):
                    candidates = {
                        item.id
                        for alias, alias_items in choices.items()
                        if alias.startswith(word)
                        or any(part.startswith(word) for part in alias.split())
                        for item in alias_items
                    }
                    if len(candidates) == 1:
                        prefix_ids.update(candidates)
                selected = [item.instrument for item in ranked if item.instrument.id in prefix_ids]
            if not selected:
                return None, "I couldn't match that to one option."

    if not selected or len(selected) > settings.market_data.max_batch_size:
        return None, f"Choose between one and {settings.market_data.max_batch_size} instruments."
    return [str(item.id) for item in selected], None


def parse_instrument_selection(
    raw: str,
    context_data: dict | InvestmentContext | None,
    answers: dict | None = None,
) -> list[str] | None:
    if not context_data:
        return None
    try:
        context = (
            context_data
            if isinstance(context_data, InvestmentContext)
            else InvestmentContext.model_validate(context_data)
        )
    except (TypeError, ValueError):
        return None
    parsed, error = _parse_answer("instruments", raw, context, answers or {})
    return parsed if error is None else None


def _widget_from_scenario(
    scenario,
    ranked_instruments: list[RankedInstrument],
) -> InvestmentPlanWidget:
    disclaimer = (
        "Illustrative scenario only. No trade has been executed. This is general financial "
        "guidance, not professional financial advice."
    )
    ranking_by_id = {item.instrument.id: item for item in ranked_instruments}
    return InvestmentPlanWidget(
        payload=InvestmentPlanPayload(
            confirmed_amount=float(scenario.confirmed_amount),
            currency="EGP",
            allocations=[
                InvestmentPlanAllocationPayload(
                    instrument_id=item.instrument_id,
                    instrument_code=item.instrument_code,
                    display_name=item.display_name,
                    asset_class=item.asset_class,
                    percentage=float(item.percentage),
                    target_amount=float(item.target_amount),
                    unit_price=float(item.unit_price),
                    price_currency="EGP",
                    unit=item.unit,
                    price_type=item.price_type,
                    minimum_increment=float(item.minimum_increment),
                    quantity=float(item.quantity),
                    actual_allocated_amount=float(item.actual_allocated_amount),
                    unallocated_remainder=float(item.unallocated_remainder),
                    observed_at=item.observed_at,
                    source=item.source,
                    mode=item.mode,
                    priority=ranking_by_id[item.instrument_id].priority,
                    match_factors=list(ranking_by_id[item.instrument_id].match_factors),
                )
                for item in scenario.allocations
            ],
            total_allocated=float(scenario.total_allocated),
            total_remainder=float(scenario.total_remainder),
            disclaimer=disclaimer,
        )
    )


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


async def investment_plan_node(state: ConversationState) -> dict:
    context = InvestmentContext.model_validate(state.get("investment_context") or {})
    answers = dict(state.get("investment_answers") or {})
    attempts = state.get("investment_validation_attempts", 0)
    reason = state.get("investment_validation_reason")

    question_id = next((item for item in _QUESTION_ORDER if item not in answers), None)
    if question_id is not None:
        raw = interrupt(
            {
                "question_id": question_id,
                "text": _question_text(question_id, context, reason, answers),
            }
        )
        parsed, error = _parse_answer(question_id, str(raw), context, answers)
        if error:
            attempts += 1
            if attempts >= MAX_VALIDATION_ATTEMPTS:
                return {
                    "messages": [
                        AIMessage(
                            content=(
                                "I couldn't confirm that part of the investment scenario, so I "
                                "stopped without requesting prices or creating an allocation."
                            )
                        )
                    ],
                    "stage": "investment_plan_cancelled",
                    "investment_validation_attempts": 0,
                    "investment_validation_reason": None,
                }
            return {
                "messages": [HumanMessage(content=str(raw))],
                "stage": "investment_planning",
                "investment_validation_attempts": attempts,
                "investment_validation_reason": error,
            }
        answers[question_id] = parsed
        return {
            "messages": [HumanMessage(content=str(raw))],
            "investment_answers": answers,
            "stage": "investment_planning",
            "investment_validation_attempts": 0,
            "investment_validation_reason": None,
        }

    if not settings.market_data.enabled:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "Market pricing is disabled in this environment, so I stopped before "
                        "creating a live-priced allocation. Your confirmed amount and preferences "
                        "were not sent to any provider."
                    )
                )
            ],
            "stage": "investment_plan_unpriced",
        }

    selected_ids = [uuid.UUID(item) for item in answers["instruments"]]
    by_id = {item.id: item for item in context.instruments}
    selected = [by_id[item] for item in selected_ids if item in by_id]
    ranked_instruments = rank_instruments(context.instruments, answers)
    priority_by_id = {item.instrument.id: item.priority for item in ranked_instruments}
    selected.sort(key=lambda item: priority_by_id[item.id])
    quote_result = await fetch_quotes(selected)
    if quote_result.unavailable or len(quote_result.quotes) != len(selected):
        quoted_ids = {quote.instrument_id for quote in quote_result.quotes}
        unavailable_ids = set(quote_result.unavailable)
        unavailable_names = [
            item.display_name
            for item in selected
            if item.id in unavailable_ids or item.id not in quoted_ids
        ]
        unavailable_text = ", ".join(unavailable_names) or "the selected opportunities"
        answers.pop("instruments", None)
        return {
            "investment_answers": answers,
            "stage": "investment_planning",
            "investment_validation_reason": (
                "I couldn't obtain a current, compatible quote for every selected "
                f"opportunity ({unavailable_text}), so no allocation was created. "
                "You can retry the same selection or choose another one."
            ),
        }

    quotes = {item.instrument_id: item for item in quote_result.quotes}
    scenario = calculate_equal_weight_scenario(
        Decimal(answers["confirmed_amount"]),
        [PricedInstrument(instrument=item, quote=quotes[item.id]) for item in selected],
    )
    widget = _widget_from_scenario(scenario, ranked_instruments)
    ranking_by_id = {item.instrument.id: item for item in ranked_instruments}
    lines = "\n\n".join(
        f"**Priority {ranking_by_id[item.instrument_id].priority} — "
        f"{item.display_name}**\n"
        f"{_match_reason_text(ranking_by_id[item.instrument_id], answers)}\n"
        f"Allocation: {_decimal_text(item.percentage)}% → "
        f"{_decimal_text(item.quantity)} {_UNIT_LABELS.get(item.unit, item.unit)} at "
        f"{_decimal_text(item.unit_price)} EGP ({item.source}, as of {item.observed_at})"
        for item in scenario.allocations
    )
    reply = with_disclaimer(
        "Here is an equal-weight illustrative scenario based on your confirmed "
        f"{scenario.confirmed_amount} EGP:\n\n{lines}\n\n"
        f"Allocated: {scenario.total_allocated} EGP; residual cash: "
        f"{scenario.total_remainder} EGP. No trade has been executed."
    )
    return {
        "messages": [AIMessage(content=reply)],
        "widget": widget,
        "stage": "investment_plan_complete",
    }
