"""Interrupt-based investment planning over curated, optionally priced instruments."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.logging import get_logger
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
from app.features.market_data.schemas import CuratedInstrument
from app.features.market_data.service import fetch_quotes

logger = get_logger(__name__)

MAX_VALIDATION_ATTEMPTS = 3
MAX_CONFIRMED_AMOUNT = Decimal("1000000000")
# The five scalar fields extraction can fill from one free-form message.
# "instruments" (the last _QUESTION_ORDER entry) is deliberately excluded —
# it depends on the live curated catalogue, so it stays on the deterministic
# regex/alias matcher below (_parse_answer) as the first, fast path: exact
# priority numbers and catalogue names/aliases resolve instantly with no LLM
# call. Only when that fails does investment_plan_node fall back to
# InstrumentSelectionExtraction (see below) — one LLM call that both
# resolves natural-language selections ("the gold one", "the recommended
# option") against the numbered list already shown, and detects an escape
# ("forget about this") — cheaper than the always-on scalar-phase extraction
# since most replies here are just a number or a name and never need it.
_SCALAR_QUESTION_IDS = (
    "confirmed_amount",
    "objective",
    "risk",
    "horizon",
    "liquidity",
)
_AMOUNT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩٫٬",
    "0123456789.,",
)
_AMOUNT_PATTERN = re.compile(r"(?<![\w.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w.,])")
_BALANCE_PERCENT_PATTERN = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|٪|percent\b|per\s+cent\b)",
    re.IGNORECASE,
)
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


class InvestmentAnswerExtraction(BaseModel):
    """Structured extraction of investment-planning answers from one
    free-form message, given which of _SCALAR_QUESTION_IDS are still
    missing. All five scalar fields are optional — a message may state
    zero, one, or several at once (e.g. an amount and an implied horizon in
    the same sentence) — investment_plan_node only ever merges in whichever
    of them are still missing, so a value for an already-answered field is
    simply ignored rather than overwriting it.

    is_escape signals the message doesn't attempt to state any of the five
    fields at all, and instead reads as a request to abandon or redirect
    the conversation (e.g. "let's forget about this", "what are my
    transactions") — investment_plan_node hands control back to Maestro for
    exactly this turn instead of force-fitting the message as an invalid
    answer. See graph.py's investment_plan -> maestro edge.
    """

    model_config = ConfigDict(extra="forbid")

    is_escape: bool = Field(
        description=(
            "True if the message does not state any of the fields below and "
            "instead reads as a request to abandon or redirect the "
            "conversation, rather than an attempt to answer."
        )
    )
    confirmed_amount: float | None = Field(
        default=None,
        description=(
            "A single unambiguous EGP amount stated in the message. Null if "
            "no amount is stated, or the amount is ambiguous (e.g. a range)."
        ),
    )
    objective: Literal["preserve_value", "balanced_growth", "income"] | None = Field(
        default=None, description="What the money should do for the user, or null."
    )
    risk: Literal["low", "moderate", "high"] | None = Field(
        default=None, description="Comfort with price movement, or null."
    )
    horizon: Literal["short", "medium", "long"] | None = Field(
        default=None, description="When the money might be needed, or null."
    )
    liquidity: Literal["low", "medium", "high"] | None = Field(
        default=None, description="How quickly access might be needed, or null."
    )


# Mock mode has no real model to call, but unlike plan/service.py's
# extract_stated_goal (a strictly-additive convenience that's fine to be
# inert offline), extraction is now the *only* path that ever fills a
# scalar answer — an inert mock branch would make investment planning's
# scalar phase entirely non-functional offline/in CI, not just untested.
# So mock mode reuses _parse_answer's existing, already-proven per-field
# regex/alias matching independently against each still-missing field
# instead of calling a model — the deterministic offline substitute for
# "does this message support this field", one field at a time, same as a
# real extraction call would judge each field.
_MOCK_ESCAPE_KEYWORDS = ("forget", "cancel", "never mind", "nevermind", "stop this")


def _mock_extract_investment_answers(
    text: str, missing_fields: list[str], context: InvestmentContext, answers: dict
) -> InvestmentAnswerExtraction:
    fields: dict[str, float | str] = {}
    for field_id in missing_fields:
        parsed, error = _parse_answer(field_id, text, context, answers)
        if error is not None or parsed is None:
            continue
        fields[field_id] = float(parsed) if field_id == "confirmed_amount" else parsed
    is_escape = not fields and any(keyword in text.casefold() for keyword in _MOCK_ESCAPE_KEYWORDS)
    return InvestmentAnswerExtraction(is_escape=is_escape, **fields)  # type: ignore[arg-type]


async def _extract_investment_answers(
    text: str, missing_fields: list[str], context: InvestmentContext, answers: dict
) -> InvestmentAnswerExtraction | None:
    """Runs the structured extraction call for one resumed message against
    whichever scalar fields are still missing. Returns None on any
    real-provider failure, which falls back to investment_plan_node's
    existing invalid-attempt handling rather than raising and losing the
    user's turn.

    Tagged with INTERNAL_CALL_TAG: this call's raw structured-output JSON
    is never the user-facing reply, but investment_plan (unlike maestro) is
    itself a service.py _LEAF_NODES member — without the tag, this call's
    output would otherwise be indistinguishable, in the outer
    stream_mode="messages" stream, from a genuine specialist reply,
    corrupting both the agent_selected event and the token stream."""
    remaining_fields = list(missing_fields)
    deterministic_amount: float | None = None
    relative_amount_recognized = False
    if "confirmed_amount" in remaining_fields:
        relative_amount, relative_error = _parse_balance_relative_amount(text, context)
        if relative_amount is not None or relative_error is not None:
            # A percentage/fraction must never fall through and be mistaken
            # for a literal amount ("30%" becoming 30 EGP). Valid relative
            # amounts are calculated locally with Decimal; invalid ones stay
            # unanswered and are reprompted.
            relative_amount_recognized = True
            remaining_fields.remove("confirmed_amount")
            if relative_amount is not None:
                deterministic_amount = float(relative_amount)

    if settings.chat_model.use_mock:
        result = _mock_extract_investment_answers(text, remaining_fields, context, answers)
        if relative_amount_recognized:
            return result.model_copy(
                update={
                    "confirmed_amount": deterministic_amount,
                    "is_escape": False if deterministic_amount is not None else result.is_escape,
                }
            )
        return result

    if not remaining_fields:
        return InvestmentAnswerExtraction(
            is_escape=False,
            confirmed_amount=deterministic_amount,
        )

    from langchain_core.messages import HumanMessage as LLMHumanMessage
    from langchain_core.messages import SystemMessage

    from app.core.llm import INTERNAL_CALL_TAG, get_chat_model
    from app.features.chat.prompts import (
        get_investment_extraction_human_prompt,
        get_investment_extraction_system_prompt,
    )

    try:
        system_prompt = get_investment_extraction_system_prompt().render()
        human_prompt = get_investment_extraction_human_prompt().render(
            message=text, missing_fields=remaining_fields
        )
        structured_llm = get_chat_model().with_structured_output(InvestmentAnswerExtraction)
        raw_result = await structured_llm.ainvoke(
            [SystemMessage(content=system_prompt), LLMHumanMessage(content=human_prompt)],
            config={"tags": [INTERNAL_CALL_TAG]},
        )
        result = (
            raw_result
            if isinstance(raw_result, InvestmentAnswerExtraction)
            else InvestmentAnswerExtraction.model_validate(raw_result)
        )
        if relative_amount_recognized:
            return result.model_copy(
                update={
                    "confirmed_amount": deterministic_amount,
                    "is_escape": False if deterministic_amount is not None else result.is_escape,
                }
            )
        return result
    except Exception:
        logger.exception("investment_answer_extraction_failed")
        if deterministic_amount is not None:
            return InvestmentAnswerExtraction(
                is_escape=False,
                confirmed_amount=deterministic_amount,
            )
        return None


class InstrumentSelectionExtraction(BaseModel):
    """Structured match of one resumed message against the numbered list of
    instrument options already shown this turn (see _selection_options_text)
    — the fallback path used only once the fast deterministic matcher
    (_parse_answer's "instruments" branch: exact priority numbers, catalogue
    names/aliases) fails to match anything.

    selected_priorities names option numbers from that same numbered list,
    never a raw catalogue id — the model was only ever shown numbers and
    names, so it can only refer back to what it saw.

    is_escape mirrors InvestmentAnswerExtraction's semantics: true when the
    message doesn't attempt to select an option at all and instead reads as
    a request to abandon or redirect the conversation.
    """

    model_config = ConfigDict(extra="forbid")

    is_escape: bool = Field(
        description=(
            "True if the message does not select any of the numbered options "
            "and instead reads as a request to abandon or redirect the "
            "conversation, rather than an attempt to choose."
        )
    )
    selected_priorities: list[int] = Field(
        default_factory=list,
        description=(
            "Priority numbers from the shown list that the message selects, in "
            "the order mentioned. Empty if the message doesn't clearly select "
            "any shown option."
        ),
    )


def _mock_extract_instrument_selection(
    text: str, ranked: list[RankedInstrument], context: InvestmentContext, answers: dict
) -> InstrumentSelectionExtraction:
    """Mock-mode substitute — reuses _parse_answer's already-proven
    deterministic matcher (same one the real fast path already tried and
    failed with) rather than a second bespoke offline matcher; only reached
    in tests via a phrasing that path can't resolve either, same as the
    real fallback is only reached after the same failure."""
    parsed, error = _parse_answer("instruments", text, context, answers)
    if error is None and parsed:
        priority_by_id = {str(item.instrument.id): item.priority for item in ranked}
        priorities = [priority_by_id[item] for item in parsed if item in priority_by_id]
        return InstrumentSelectionExtraction(is_escape=False, selected_priorities=priorities)
    is_escape = any(keyword in text.casefold() for keyword in _MOCK_ESCAPE_KEYWORDS)
    return InstrumentSelectionExtraction(is_escape=is_escape, selected_priorities=[])


async def _extract_instrument_selection(
    text: str, ranked: list[RankedInstrument], context: InvestmentContext, answers: dict
) -> InstrumentSelectionExtraction | None:
    """Runs the structured instrument-selection-matching call for one
    resumed message that the deterministic matcher couldn't resolve.
    Returns None on any real-provider failure, which falls back to
    investment_plan_node's existing invalid-attempt handling.

    Tagged with INTERNAL_CALL_TAG for the same reason as
    _extract_investment_answers — investment_plan is a service.py
    _LEAF_NODES member, so an untagged call's raw output would otherwise be
    indistinguishable from a genuine specialist reply in the outer
    stream_mode="messages" stream."""
    if settings.chat_model.use_mock:
        return _mock_extract_instrument_selection(text, ranked, context, answers)

    from langchain_core.messages import HumanMessage as LLMHumanMessage
    from langchain_core.messages import SystemMessage

    from app.core.llm import INTERNAL_CALL_TAG, get_chat_model
    from app.features.chat.prompts import (
        get_instrument_selection_human_prompt,
        get_instrument_selection_system_prompt,
    )

    try:
        system_prompt = get_instrument_selection_system_prompt().render()
        human_prompt = get_instrument_selection_human_prompt().render(
            message=text,
            options=[
                {
                    "priority": item.priority,
                    "display_name": item.instrument.display_name,
                    # Mirrors _selection_options_text's own "(Recommended)"
                    # label on the top-ranked option — without it, a reply
                    # like "the recommended one" has nothing in this prompt
                    # to resolve against, since the model was never told
                    # which option the user actually saw marked that way.
                    "is_recommended": index == 0,
                }
                for index, item in enumerate(ranked)
            ],
        )
        structured_llm = get_chat_model().with_structured_output(InstrumentSelectionExtraction)
        raw_result = await structured_llm.ainvoke(
            [SystemMessage(content=system_prompt), LLMHumanMessage(content=human_prompt)],
            config={"tags": [INTERNAL_CALL_TAG]},
        )
        return (
            raw_result
            if isinstance(raw_result, InstrumentSelectionExtraction)
            else InstrumentSelectionExtraction.model_validate(raw_result)
        )
    except Exception:
        logger.exception("instrument_selection_extraction_failed")
        return None


def _validate_extracted_amount(value: float) -> Decimal | None:
    """Applies the same bounds this field always enforced (see
    _parse_answer's confirmed_amount branch) to an LLM-extracted value — an
    out-of-range or non-finite extraction is treated as not having been
    extracted at all, rather than silently accepted or erroring the turn."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0 or amount > MAX_CONFIRMED_AMOUNT:
        return None
    return amount.quantize(Decimal("0.01"))


def _merge_extracted_answers(
    extraction: InvestmentAnswerExtraction | None,
    missing_fields: list[str],
    answers: dict,
) -> bool:
    """Merge only valid, still-missing scalar facts into questionnaire state."""
    if extraction is None:
        return False
    filled_any = False
    for field_id in missing_fields:
        value = getattr(extraction, field_id)
        if value is None:
            continue
        if field_id == "confirmed_amount":
            decimal_value = _validate_extracted_amount(value)
            if decimal_value is None:
                continue
            answers[field_id] = str(decimal_value)
        else:
            answers[field_id] = value
        filled_any = True
    return filled_any


async def extract_initial_investment_answers(
    text: str,
    context: InvestmentContext,
) -> dict:
    """Capture facts from the request that first opened the questionnaire.

    LangGraph pauses the investment node before it receives a resume value,
    so without this handoff a request such as "invest 30% in gold" is used
    only for routing and both facts disappear. Maestro calls this once after
    deriving the live investment context and persists the result before the
    first interrupt.
    """
    answers: dict = {}
    extraction = await _extract_investment_answers(
        text,
        list(_SCALAR_QUESTION_IDS),
        context,
        answers,
    )
    _merge_extracted_answers(extraction, list(_SCALAR_QUESTION_IDS), answers)

    selected, error = _parse_answer("instruments", text, context, answers)
    if error is None and selected:
        answers["instruments"] = selected
    return answers


# Short labels for the numbered list a multi-field question renders as —
# purely cosmetic, never parsed: the resumed answer is matched against
# _CHOICE_ALIASES/_AMOUNT_PATTERN, never against this display text.
_SCALAR_FIELD_LABELS = {
    "confirmed_amount": "Amount",
    "objective": "Goal",
    "risk": "Risk",
    "horizon": "Horizon",
    "liquidity": "Liquidity",
}


def _consolidated_question_text(
    missing_scalar_ids: list[str],
    context: InvestmentContext,
    reason: str | None,
    answers: dict,
) -> str:
    """Builds one question covering every still-missing scalar field —
    reusing _question_text's existing per-field phrasing (including the
    surplus-aware amount framing) rather than duplicating it. `reason` (set
    only when the previous turn's message stated none of the missing fields
    at all — see investment_plan_node) applies to the whole batch rather
    than one specific field, since a consolidated question doesn't
    attribute failure to a single field.

    A single missing field reads fine as one plain sentence, so that case
    is left untouched. Two or more read as an undifferentiated wall of
    paragraphs when just concatenated — each one numbered and given a bold
    one-word label turns it into a scannable list instead."""
    if len(missing_scalar_ids) == 1:
        return _question_text(missing_scalar_ids[0], context, reason, answers)
    parts = [
        f"**{index}. {_SCALAR_FIELD_LABELS[field_id]}**\n"
        f"{_question_text(field_id, context, None, answers)}"
        for index, field_id in enumerate(missing_scalar_ids, start=1)
    ]
    body = "\n\n".join(parts)
    if reason:
        return f"{reason}\n\n{body}"
    return f"A few things to plan this:\n\n{body}"


# The four suitability criteria in the same order questions ask them —
# shared by both the positive ("matches") and mismatch ("less fit")
# reasoning below so the two stay in sync.
_MATCH_FIELD_ORDER = ("objective", "risk", "horizon", "liquidity")
_OBJECTIVE_DISPLAY = {
    "preserve_value": "preserving value",
    "balanced_growth": "balanced growth",
    "income": "income",
}
_HORIZON_DISPLAY = {
    "short": "a short-term horizon",
    "medium": "a medium-term horizon",
    "long": "a long-term horizon",
}


def _join_natural(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _positive_phrases(ranked: RankedInstrument, answers: dict) -> list[str]:
    """Facts about which of the user's stated preferences this instrument
    exactly matches, driven entirely by rank_instruments' own match_factors
    — never a separate judgment call."""
    objective = str(answers.get("objective", "")).replace("_", " ")
    phrase_by_factor = {
        "objective": f"your {objective} goal",
        "risk": f"your {answers.get('risk', '')} risk tolerance",
        "horizon": f"your {answers.get('horizon', '')}-term horizon",
        "liquidity": f"your {answers.get('liquidity', '')} liquidity need",
    }
    return [
        phrase_by_factor[factor] for factor in _MATCH_FIELD_ORDER if factor in ranked.match_factors
    ]


def _instrument_objectives_display(instrument: CuratedInstrument) -> str:
    labels = [_OBJECTIVE_DISPLAY.get(item, item) for item in instrument.objectives]
    return _join_natural(labels) if labels else "no stated objective"


def _instrument_horizons_display(instrument: CuratedInstrument) -> str:
    labels = [_HORIZON_DISPLAY.get(item, item) for item in instrument.horizons]
    return _join_natural(labels) if labels else "no stated horizon"


def _mismatch_reasons(ranked: RankedInstrument, answers: dict) -> list[str]:
    """Facts about which of the user's stated preferences this instrument
    does NOT match, read directly off the catalogue's own suitability
    metadata (never invented) — only for a criterion the user actually
    answered and the catalogue actually states a value for, so a field with
    no stated preference or missing catalogue metadata is silently skipped
    rather than guessed at."""
    instrument = ranked.instrument
    reasons = []
    objective = answers.get("objective")
    if objective and "objective" not in ranked.match_factors and instrument.objectives:
        reasons.append(
            f"targets {_instrument_objectives_display(instrument)}, not your "
            f"{_OBJECTIVE_DISPLAY.get(str(objective), str(objective))} goal"
        )
    risk = answers.get("risk")
    if risk and "risk" not in ranked.match_factors and instrument.risk_level:
        reasons.append(f"carries {instrument.risk_level} risk, not your {risk} risk tolerance")
    horizon = answers.get("horizon")
    if horizon and "horizon" not in ranked.match_factors and instrument.horizons:
        reasons.append(
            f"suits {_instrument_horizons_display(instrument)}, not your {horizon}-term goal"
        )
    liquidity = answers.get("liquidity")
    if liquidity and "liquidity" not in ranked.match_factors and instrument.liquidity_level:
        reasons.append(
            f"offers {instrument.liquidity_level} liquidity, not your {liquidity} liquidity need"
        )
    return reasons


def _match_reason_text(ranked: RankedInstrument, answers: dict) -> str:
    """Positive-only reasoning for the final allocation summary, where every
    listed instrument is one the user already chose — there's nothing to
    compare it against, so only why it fits is relevant."""
    if ranked.match_factors == ("closest_available",):
        return "The closest available match to your stated preferences."
    phrases = _positive_phrases(ranked, answers)
    return f"Matches {_join_natural(phrases)}." if phrases else "Matches your stated preferences."


def _recommended_reason_text(ranked: RankedInstrument, answers: dict) -> str:
    if ranked.match_factors == ("closest_available",):
        return (
            "No catalogue option closely matches every preference you gave — this is the "
            "closest available choice."
        )
    phrases = _positive_phrases(ranked, answers)
    if not phrases:
        return "The best overall fit among the available options."
    return f"Matches {_join_natural(phrases)}."


def _less_fit_reason_text(ranked: RankedInstrument, answers: dict) -> str:
    """Lowercase, no trailing period — always read inline after a "less fit:"
    lead-in in the bullet list below, never as its own standalone sentence."""
    reasons = _mismatch_reasons(ranked, answers)
    if not reasons:
        return "a lower overall fit than the recommended option, based on the same catalogue data"
    return _join_natural(reasons[:2])


def _selection_options_text(ranked: list[RankedInstrument], answers: dict) -> str:
    """The top-ranked option gets its own bold, fully-explained block —
    the single Recommended choice, with the full factual case for it.
    Every other option is demoted to one compact bullet each: a name and
    the specific stated preferences it doesn't match, rather than a
    same-sized block that visually competes with the actual recommendation."""
    if not ranked:
        return ""
    top, *rest = ranked
    lines = [
        f"**Recommended: {top.instrument.display_name}** (Priority {top.priority})",
        _recommended_reason_text(top, answers),
    ]
    if rest:
        lines.append("")
        lines.append("Other options:")
        lines.extend(
            f"- **{item.instrument.display_name}** (Priority {item.priority}) — "
            f"less fit: {_less_fit_reason_text(item, answers)}"
            for item in rest
        )
    return "\n".join(lines)


def _money_display(value: Decimal | None) -> str:
    return "not available" if value is None else f"{value:,.0f}"


def _balance_display(value: Decimal) -> str:
    return f"{value:,.2f}"


def _question_text(
    question_id: str,
    context: InvestmentContext,
    reason: str | None,
    answers: dict | None = None,
) -> str:
    if question_id == "confirmed_amount":
        if reason:
            relative_hint = (
                ", **30%**, or **half of my balance**"
                if context.current_balance is not None
                else ""
            )
            return f"{reason}\n\nTry one amount, such as **1,200 EGP**{relative_hint}."
        if context.current_balance is not None:
            currency = context.current_balance_currency or "EGP"
            return (
                f"Your current {currency} balance is "
                f"**{_balance_display(context.current_balance)} {currency}**.\n\n"
                "How much should this plan use? You can give an exact amount, "
                "a percentage such as **30%**, or a fraction such as "
                "**half of my balance**."
            )
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
            "How much price movement are you comfortable with: **low**, **moderate**, or **high**?"
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
            "How quickly might you need access: **quickly**, **some flexibility**, or **not soon**?"
        )

    ranked = rank_instruments(context.instruments[: settings.market_data.max_batch_size], answers)
    choices = _selection_options_text(ranked, answers or {})
    call_to_action = (
        "Reply with the recommended option, another priority number or name, or describe "
        "which one you'd like — up to three."
    )
    if reason:
        return f"{reason}\n\n{choices}\n\n{call_to_action}"
    return (
        "Here's what fits your preferences best:\n\n"
        f"{choices}\n\n"
        f"This is based on your preferences, not predicted returns. {call_to_action}"
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


def _parse_balance_relative_amount(
    raw: str,
    context: InvestmentContext,
) -> tuple[Decimal | None, str | None]:
    """Resolve a percentage/fraction of the live EGP balance locally.

    Returning an error also signals that relative wording was recognized, so
    callers can prevent a percentage such as ``30%`` from falling through to
    the literal-number parser and becoming 30 EGP.
    """
    normalized = raw.translate(_AMOUNT_TRANSLATION)
    lowered = normalized.casefold()
    candidates: list[Decimal] = [
        Decimal(match) for match in _BALANCE_PERCENT_PATTERN.findall(normalized)
    ]

    balance_mentioned = bool(re.search(r"\bbalance\b", lowered))
    compact = re.sub(r"[^\w\s]+", " ", lowered)
    compact = re.sub(r"\s+", " ", compact).strip()

    if re.search(r"\bhalf\b", lowered) and (
        balance_mentioned or compact in {"half", "a half", "one half"}
    ):
        candidates.append(Decimal("50"))
    if re.search(r"\bquarter\b", lowered) and (
        balance_mentioned or compact in {"quarter", "a quarter", "one quarter"}
    ):
        candidates.append(Decimal("25"))
    if re.search(r"\b(?:all|everything|full|whole)\b", lowered) and (
        balance_mentioned or compact in {"all", "everything"}
    ):
        candidates.append(Decimal("100"))

    if not candidates:
        return None, None
    if len(candidates) != 1:
        return None, "Please provide one percentage or fraction of your balance."

    percentage = candidates[0]
    if not percentage.is_finite() or percentage <= 0 or percentage > 100:
        return None, "The balance percentage must be greater than 0 and no more than 100%."
    if context.current_balance is None:
        return None, "I couldn't determine your current EGP balance for that calculation."
    if context.current_balance <= 0:
        return None, "Your current EGP balance must be greater than zero for that calculation."

    amount = (context.current_balance * percentage / Decimal("100")).quantize(Decimal("0.01"))
    if amount > MAX_CONFIRMED_AMOUNT:
        return None, "The calculated amount must not exceed 1,000,000,000 EGP."
    return amount, None


def _parse_answer(
    question_id: str,
    raw: str,
    context: InvestmentContext,
    answers: dict | None = None,
):
    cleaned = raw.strip()
    if question_id == "confirmed_amount":
        relative_amount, relative_error = _parse_balance_relative_amount(cleaned, context)
        if relative_amount is not None or relative_error is not None:
            return (
                str(relative_amount) if relative_amount is not None else None,
                relative_error,
            )
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

    missing = [item for item in _QUESTION_ORDER if item not in answers]
    scalar_missing = [item for item in missing if item != "instruments"]

    if scalar_missing:
        raw = interrupt(
            {
                "question_id": "investment_scalars",
                "text": _consolidated_question_text(scalar_missing, context, reason, answers),
            }
        )
        extraction = await _extract_investment_answers(str(raw), scalar_missing, context, answers)

        if extraction is not None and extraction.is_escape:
            # Hand this turn back to Maestro instead of force-fitting the
            # message as an invalid answer — see graph.py's
            # investment_plan -> maestro edge. investment_answers is
            # deliberately untouched: coming back to investment planning
            # later (PR 1's guard) resumes right where this left off.
            return {
                "messages": [HumanMessage(content=str(raw))],
                "stage": "investment_plan_escaped",
                "investment_validation_attempts": 0,
                "investment_validation_reason": None,
            }

        filled_any = _merge_extracted_answers(extraction, scalar_missing, answers)

        if not filled_any:
            # Not an escape, and nothing this turn's message stated matched
            # any still-missing field — same MAX_VALIDATION_ATTEMPTS budget
            # as before, but now shared across the whole batch of missing
            # fields rather than one specific field: any turn that makes
            # partial progress (filled_any=True) resets it, so a user who
            # keeps supplying *something* useful never gets cut off.
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
                "investment_validation_reason": (
                    "I couldn't confirm any of that — could you try again?"
                ),
            }

        return {
            "messages": [HumanMessage(content=str(raw))],
            "investment_answers": answers,
            "stage": "investment_planning",
            "investment_validation_attempts": 0,
            "investment_validation_reason": None,
        }

    # Only "instruments" can remain here. _parse_answer's deterministic
    # catalogue-aware matcher runs first — exact priority numbers and
    # catalogue names/aliases resolve instantly, no LLM call, unchanged from
    # before this feature. Only on a match failure does this fall back to
    # InstrumentSelectionExtraction, which both resolves a natural-language
    # selection ("the gold one", "the recommended option") against the same
    # numbered list already shown, and detects an escape ("forget about
    # this", "what are my transactions") — without it, either of those would
    # otherwise just loop the same question instead of resolving the pick or
    # handing back to Maestro.
    question_id = missing[0] if missing else None
    if question_id is not None:
        raw = interrupt(
            {
                "question_id": question_id,
                "text": _question_text(question_id, context, reason, answers),
            }
        )
        parsed, error = _parse_answer(question_id, str(raw), context, answers)
        if error and question_id == "instruments":
            ranked = rank_instruments(
                context.instruments[: settings.market_data.max_batch_size], answers
            )
            instrument_extraction = await _extract_instrument_selection(
                str(raw), ranked, context, answers
            )
            if instrument_extraction is not None and instrument_extraction.is_escape:
                return {
                    "messages": [HumanMessage(content=str(raw))],
                    "stage": "investment_plan_escaped",
                    "investment_validation_attempts": 0,
                    "investment_validation_reason": None,
                }
            if instrument_extraction is not None and instrument_extraction.selected_priorities:
                instrument_by_priority = {item.priority: item.instrument for item in ranked}
                selected_instrument_ids: list[str] = []
                for priority in instrument_extraction.selected_priorities:
                    instrument = instrument_by_priority.get(priority)
                    if instrument is not None and str(instrument.id) not in selected_instrument_ids:
                        selected_instrument_ids.append(str(instrument.id))
                if (
                    selected_instrument_ids
                    and len(selected_instrument_ids) <= settings.market_data.max_batch_size
                ):
                    parsed, error = selected_instrument_ids, None
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
