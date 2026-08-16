"""US1 Unit test: Maestro intent classification (mock mode)."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.features.chat.agents.maestro import _parse_llm_intent, classify_intent, maestro_node


@pytest.mark.parametrize(
    "message,expected",
    [
        ("how much did I spend on food last month", "analysis"),
        ("show me my transactions", "analysis"),
        ("what were my expenses", "analysis"),
        ("help me budget for next month", "planning"),
        ("I want to plan my spending", "planning"),
        ("create a budget for me", "planning"),
        ("which credit card should I get", "recommendation"),
        ("what savings account is best", "recommendation"),
        ("recommend a product for me", "recommendation"),
        ("hello there", "general"),
        ("what can you do", "general"),
        ("thank you", "general"),
    ],
)
def test_classify_intent(message: str, expected: str):
    result = classify_intent(message)
    assert result == expected


# Real-LLM classification path (maestro_node's `else` branch, chat_model.use_mock=False)
# was previously untested — only classify_intent()'s mock-mode keyword matcher above
# had coverage. These exercise _parse_llm_intent() directly against the kind of
# not-quite-bare-word replies a real model returns, which the old exact-match check
# (`classified in _INTENT_KEYWORDS`) silently dropped to "general".
@pytest.mark.parametrize(
    "raw",
    [
        "analysis",
        "Analysis",
        "Analysis.",
        "'analysis'",
        '"analysis"',
        "the answer is analysis",
    ],
)
def test_parse_llm_intent_tolerates_a_dirty_reply(raw: str):
    result = _parse_llm_intent(raw, "what are my recent transactions?")
    assert result == "analysis"


def test_parse_llm_intent_falls_back_to_keywords_when_unparsable():
    # A reply with none of the three intent words in it at all — falls back
    # to the same keyword matcher mock mode uses, rather than "general".
    result = _parse_llm_intent("sure, I can help with that", "recommend a savings account")
    assert result == "recommendation"


@pytest.mark.parametrize(
    "raw",
    ["general", "General", "General.", "'general'", "the answer is general"],
)
def test_parse_llm_intent_trusts_a_clean_general_reply(raw: str):
    # Regression test for a real bug: the LLM correctly classified "i want a
    # plan to rob a bank" as "general" (per the illegal/harmful-act routing
    # instruction in intent_classification.jinja2), but "general" wasn't in
    # _VALID_INTENTS, so it was treated as unparsed and fell through to
    # classify_intent() — a blind keyword scan of the ORIGINAL message, where
    # the literal word "plan" silently overrode the LLM's correct answer
    # back to "planning". A clean "general" reply must be trusted as-is,
    # exactly like the three task intents already are.
    result = _parse_llm_intent(raw, "i want a plan to rob a bank")
    assert result == "general"


def test_parse_llm_intent_falls_back_to_general_when_truly_unclassifiable():
    result = _parse_llm_intent("sure, I can help with that", "hello there")
    assert result == "general"


# ── classify_intent: history fallback for elliptical follow-ups ─────────────


def test_classify_intent_falls_back_to_history_when_message_has_no_keywords():
    # "what about this month ?" alone carries no _INTENT_KEYWORDS match.
    result = classify_intent(
        "what about this month ?", history="human: what did i spend on the most last month?"
    )
    assert result == "analysis"


def test_classify_intent_prefers_message_keywords_over_history():
    result = classify_intent(
        "which credit card should I get", history="human: what did i spend on the most last month?"
    )
    assert result == "recommendation"


def test_classify_intent_general_when_neither_message_nor_history_match():
    result = classify_intent("hello there", history="human: hi\nai: hello, how can I help?")
    assert result == "general"


@pytest.mark.asyncio
async def test_maestro_node_uses_history_for_elliptical_followup_in_mock_mode():
    state = {
        "messages": [
            HumanMessage(content="what did i spend on the most last month?"),
            AIMessage(content="I don't have that data yet. Backend is unavailable."),
            HumanMessage(content="what about this month ?"),
        ],
        "stage": "",
        "questions_asked": 0,
    }
    result = await maestro_node(state)
    assert result["intent"] == "analysis"
