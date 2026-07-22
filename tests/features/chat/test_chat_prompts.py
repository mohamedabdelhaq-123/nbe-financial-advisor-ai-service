"""US2 golden-string tests: chat prompt templates preserve hardcoded wording (FR-005)."""

from app.features.chat.prompts import (
    get_grounded_analysis_prompt,
    get_intent_classification_prompt,
    get_summary_prompt,
)

_GOLDEN_SUMMARY = (
    "Summarise the following conversation turns concisely:\n\n" "human: hello\n" "ai: hi there"
)

_GOLDEN_INTENT = (
    "Classify the intent of this user message into one of: "
    "analysis, planning, recommendation, general.\n"
    "Message: How much did I spend?\n"
    "Respond with ONLY the intent word."
)

_GOLDEN_ANALYSIS = (
    "User asked about their spending. Here are their transactions:\n"
    "- Coffee (food): 5.00\n"
    "- Rent (housing): 1000.00\n"
    "Provide a grounded summary. Cite specific figures only from this data. "
    "State 'I don't have that data yet' for anything not covered."
)


def test_summary_prompt_matches_hardcoded_output():
    """US2 acceptance #1 — summarization template is byte-for-byte the old inline prompt."""
    rendered = get_summary_prompt().render(turns=["human: hello", "ai: hi there"])
    assert rendered == _GOLDEN_SUMMARY


def test_intent_classification_prompt_matches_hardcoded_output():
    """US2 acceptance #2 — classification template matches and still names the fixed labels."""
    rendered = get_intent_classification_prompt().render(message="How much did I spend?")
    assert rendered == _GOLDEN_INTENT
    # The fixed intent-label set must remain present verbatim in the rendered text.
    assert "analysis, planning, recommendation, general" in rendered


def test_grounded_analysis_prompt_matches_hardcoded_output():
    """US2 acceptance #3 — analysis template matches and still enforces grounding."""
    data_context = "- Coffee (food): 5.00\n- Rent (housing): 1000.00"
    rendered = get_grounded_analysis_prompt().render(data_context=data_context)
    assert rendered == _GOLDEN_ANALYSIS
    # The grounding instruction must remain present verbatim in the rendered text.
    assert "Cite specific figures only from this data" in rendered
    assert "I don't have that data yet" in rendered
