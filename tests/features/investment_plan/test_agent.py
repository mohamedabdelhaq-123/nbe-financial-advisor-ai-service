import datetime
import uuid
from decimal import Decimal

import pytest

from app.core.config import settings
from app.features.chat.agents import investment as investment_module
from app.features.chat.agents.investment import (
    _parse_answer,
    _question_text,
    investment_plan_node,
)
from app.features.investment_plan.ranking import rank_instruments
from app.features.investment_plan.schemas import InvestmentContext
from app.features.market_data.schemas import CuratedInstrument, MarketQuote, QuoteBatchResult


def _instrument(asset_class="gold") -> CuratedInstrument:
    semantics = {
        "gold": ("spot", "gram_24k", "0.01"),
        "fund": ("market_price", "fund_unit", "1"),
        "currency": ("customer_buy_rate", "USD", "1"),
    }
    price_type, unit, increment = semantics[asset_class]
    suitability = {
        "gold": {
            "aliases": ["gold", "24k gold", "ذهب", "الذهب"],
            "objectives": ["preserve_value", "balanced_growth"],
            "risk_level": "moderate",
            "horizons": ["medium", "long"],
            "liquidity_level": "medium",
        },
        "fund": {
            "aliases": ["etf", "صندوق"],
            "objectives": ["balanced_growth"],
            "risk_level": "high",
            "horizons": ["long"],
            "liquidity_level": "high",
        },
        "currency": {
            "aliases": ["usd", "dollar", "دولار", "الدولار"],
            "objectives": ["preserve_value"],
            "risk_level": "moderate",
            "horizons": ["short", "medium"],
            "liquidity_level": "high",
        },
    }
    return CuratedInstrument(
        id=uuid.uuid4(),
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
        **suitability[asset_class],
    )


def _state(instruments: list[CuratedInstrument]) -> dict:
    return {
        "user_id": uuid.uuid4(),
        "investment_context": InvestmentContext(instruments=instruments).model_dump(mode="json"),
        "investment_answers": {
            "confirmed_amount": "10000.00",
            "objective": "balanced_growth",
            "risk": "moderate",
            "horizon": "medium",
            "liquidity": "medium",
            "instruments": [str(item.id) for item in instruments],
        },
        "investment_validation_attempts": 0,
        "investment_validation_reason": None,
    }


def _quotes(instruments: list[CuratedInstrument]) -> QuoteBatchResult:
    now = datetime.datetime.now(datetime.timezone.utc)
    prices = {"gold": "4750", "fund": "125.50", "currency": "49.25"}
    return QuoteBatchResult(
        quotes=[
            MarketQuote(
                instrument_id=item.id,
                price=Decimal(prices[item.asset_class]),
                price_currency="EGP",
                unit=item.unit,
                price_type=item.price_type,
                observed_at=now,
                received_at=now,
                source="test-market-data",
                mode="mock",
            )
            for item in instruments
        ]
    )


def test_objective_answer_is_constrained():
    context = InvestmentContext()
    assert _parse_answer("objective", "balanced growth", context) == (
        "balanced_growth",
        None,
    )
    _, error = _parse_answer("objective", "get rich quickly", context)
    assert error == "I didn't understand the goal."


@pytest.mark.parametrize("answer", ["growth", "grow", "steady growth"])
def test_objective_accepts_natural_growth_phrases(answer):
    assert _parse_answer("objective", answer, InvestmentContext()) == (
        "balanced_growth",
        None,
    )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("1200", "1200.00"),
        ("about 1200", "1200.00"),
        ("I confirm 1,200 EGP", "1200.00"),
        ("حوالي ١٬٢٠٠ جنيه", "1200.00"),
        ("EGP 1200.50", "1200.50"),
    ],
)
def test_confirmed_amount_accepts_natural_single_amount(answer, expected):
    assert _parse_answer("confirmed_amount", answer, InvestmentContext()) == (
        expected,
        None,
    )


@pytest.mark.parametrize("answer", ["between 1000 and 1200", "1.2k", "no amount yet"])
def test_confirmed_amount_rejects_ambiguous_or_unsupported_amount(answer):
    parsed, error = _parse_answer("confirmed_amount", answer, InvestmentContext())
    assert parsed is None
    assert "one unambiguous" in error


def test_invalid_amount_reprompt_does_not_repeat_full_surplus_explanation():
    context = InvestmentContext(
        average_monthly_income=Decimal("35000"),
        average_monthly_expenses=Decimal("12000"),
        estimated_monthly_surplus=Decimal("20000"),
        currency="EGP",
        months_used=3,
    )

    prompt = _question_text(
        "confirmed_amount",
        context,
        "Please provide one unambiguous numeric EGP amount.",
    )

    assert "average income" not in prompt
    assert "1,200 EGP" in prompt


def test_initial_amount_prompt_is_scannable_and_avoids_false_precision():
    context = InvestmentContext(
        average_monthly_income=Decimal("26745.15"),
        average_monthly_expenses=Decimal("3854.81"),
        monthly_goal_commitment=Decimal("6746.44"),
        estimated_monthly_surplus=Decimal("16143.90"),
        currency="EGP",
        months_used=3,
    )

    prompt = _question_text("confirmed_amount", context, None)

    assert "**16,144 EGP left each month**" in prompt
    assert "Income 26,745 − spending 3,855 − goals 6,746" in prompt
    assert "26745.15" not in prompt
    assert "not your account balance" in prompt


@pytest.mark.parametrize(
    ("answer", "expected_asset_class"),
    [
        ("gold", "gold"),
        ("dollar", "currency"),
        ("USD", "currency"),
        ("ذهب", "gold"),
        ("صندوق", "fund"),
    ],
)
def test_instrument_selection_accepts_simple_natural_names(answer, expected_asset_class):
    instruments = [_instrument("gold"), _instrument("fund"), _instrument("currency")]
    context = InvestmentContext(instruments=instruments)

    selected, error = _parse_answer(
        "instruments",
        answer,
        context,
        {"objective": "balanced_growth", "risk": "moderate"},
    )

    assert error is None
    selected_instrument = next(item for item in instruments if str(item.id) == selected[0])
    assert selected_instrument.asset_class == expected_asset_class


def test_instrument_selection_accepts_natural_multi_choice_and_arabic_comma():
    instruments = [_instrument("gold"), _instrument("fund"), _instrument("currency")]
    context = InvestmentContext(instruments=instruments)

    english, english_error = _parse_answer("instruments", "gold and dollar", context, {})
    arabic, arabic_error = _parse_answer("instruments", "الذهب، الدولار", context, {})

    assert english_error is None
    assert arabic_error is None
    assert len(english) == 2
    assert set(arabic) == set(english)


def test_instrument_selection_accepts_ranked_option_numbers():
    instruments = [_instrument("gold"), _instrument("fund"), _instrument("currency")]
    context = InvestmentContext(instruments=instruments)
    answers = {
        "objective": "balanced_growth",
        "risk": "high",
        "horizon": "long",
        "liquidity": "high",
    }

    selected, error = _parse_answer("instruments", "1 and 3", context, answers)
    ranked = rank_instruments(instruments, answers)

    assert error is None
    assert selected == [str(ranked[0].instrument.id), str(ranked[2].instrument.id)]


def test_instrument_selection_accepts_a_normal_sentence_using_catalogue_aliases():
    instruments = [_instrument("gold"), _instrument("fund"), _instrument("currency")]
    context = InvestmentContext(instruments=instruments)

    selected, error = _parse_answer(
        "instruments",
        "Please include the gold option and the ETF",
        context,
        {},
    )

    assert error is None
    assert {item.asset_class for item in instruments if str(item.id) in selected} == {
        "gold",
        "fund",
    }


def test_instrument_selection_accepts_unique_catalogue_prefix_egx():
    fund = _instrument("fund")
    fund.display_name = "EGX30 Index ETF"
    fund.aliases = ["etf", "egx30", "egx30 etf"]
    instruments = [_instrument("gold"), fund, _instrument("currency")]

    selected, error = _parse_answer(
        "instruments",
        "egx",
        InvestmentContext(instruments=instruments),
        {"objective": "balanced_growth"},
    )

    assert error is None
    assert selected == [str(fund.id)]


def test_selection_prompt_shows_explained_priority_without_internal_codes():
    instruments = [_instrument("gold"), _instrument("fund"), _instrument("currency")]
    context = InvestmentContext(instruments=instruments)
    answers = {
        "objective": "balanced_growth",
        "risk": "high",
        "horizon": "long",
        "liquidity": "high",
    }

    prompt = _question_text("instruments", context, None, answers)

    assert "suggested priority order" in prompt
    assert "**Priority 1 — Fund instrument**" in prompt
    assert "high risk" in prompt
    assert "gold-instrument" not in prompt
    assert "simple names" not in prompt
    assert "priority numbers or names" in prompt
    assert "\n\n**Priority 2" in prompt


def test_ranking_changes_with_questionnaire_answers():
    instruments = [_instrument("gold"), _instrument("fund"), _instrument("currency")]

    growth_order = rank_instruments(
        instruments,
        {
            "objective": "balanced_growth",
            "risk": "high",
            "horizon": "long",
            "liquidity": "high",
        },
    )
    preserve_order = rank_instruments(
        instruments,
        {
            "objective": "preserve_value",
            "risk": "moderate",
            "horizon": "short",
            "liquidity": "high",
        },
    )

    assert growth_order[0].instrument.asset_class == "fund"
    assert preserve_order[0].instrument.asset_class == "currency"


@pytest.mark.asyncio
async def test_disabled_mode_stops_without_requesting_quotes(monkeypatch):
    instrument = _instrument()
    monkeypatch.setattr(settings.market_data, "enabled", False)

    async def fail_if_called(instruments):
        raise AssertionError("disabled mode must not request quotes")

    monkeypatch.setattr(investment_module, "fetch_quotes", fail_if_called)

    result = await investment_plan_node(_state([instrument]))

    assert result["stage"] == "investment_plan_unpriced"
    assert result.get("widget") is None
    assert "disabled" in result["messages"][0].content


@pytest.mark.asyncio
async def test_partial_quote_response_does_not_redistribute(monkeypatch):
    instruments = [_instrument("gold"), _instrument("fund")]
    monkeypatch.setattr(settings.market_data, "enabled", True)

    async def partial(items):
        result = _quotes(items[:1])
        result.unavailable = [items[1].id]
        return result

    monkeypatch.setattr(investment_module, "fetch_quotes", partial)

    result = await investment_plan_node(_state(instruments))

    assert result["stage"] == "investment_planning"
    assert result.get("widget") is None
    assert "instruments" not in result["investment_answers"]
    assert "no allocation was created" in result["investment_validation_reason"]
    assert instruments[1].display_name in result["investment_validation_reason"]


@pytest.mark.asyncio
async def test_complete_flow_returns_reproducible_widget(monkeypatch):
    instruments = [_instrument("gold"), _instrument("fund"), _instrument("currency")]
    monkeypatch.setattr(settings.market_data, "enabled", True)

    async def complete(items):
        return _quotes(items)

    monkeypatch.setattr(investment_module, "fetch_quotes", complete)

    result = await investment_plan_node(_state(instruments))

    assert result["stage"] == "investment_plan_complete"
    widget = result["widget"]
    assert widget.type == "investment_plan"
    assert widget.payload.confirmed_amount == 10000
    assert [item.percentage for item in widget.payload.allocations] == [33.33, 33.33, 33.34]
    assert widget.payload.total_allocated + widget.payload.total_remainder == 10000
    assert all(item.source == "test-market-data" for item in widget.payload.allocations)
    assert all(item.priority is not None for item in widget.payload.allocations)
    assert all(item.match_factors for item in widget.payload.allocations)
    assert "No trade has been executed" in result["messages"][0].content
    assert "Priority 1" in result["messages"][0].content
