"""US2 golden-string tests: chat prompt templates preserve hardcoded wording (FR-005)."""

from app.features.chat.prompts import get_intent_classification_prompt, get_summary_prompt

_GOLDEN_SUMMARY = (
    "Summarise the following conversation turns concisely:\n\nhuman: hello\nai: hi there"
)

_GOLDEN_INTENT = (
    "Classify the intent of this user message into one of: "
    "analysis, planning, recommendation, general.\n"
    "Message: How much did I spend?\n"
    "Respond with ONLY the intent word."
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
