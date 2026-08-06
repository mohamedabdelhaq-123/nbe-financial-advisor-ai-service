"""US1 Unit test: Maestro intent classification (mock mode)."""

import pytest

from app.features.chat.agents.maestro import _parse_llm_intent, classify_intent


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
        "\"analysis\"",
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


def test_parse_llm_intent_falls_back_to_general_when_truly_unclassifiable():
    result = _parse_llm_intent("sure, I can help with that", "hello there")
    assert result == "general"
