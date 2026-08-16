"""US2 golden-string tests: chat prompt templates preserve hardcoded wording (FR-005)."""

from app.features.chat.prompts import get_intent_classification_prompt, get_summary_prompt

_GOLDEN_SUMMARY = (
    "Summarise the following conversation turns concisely:\n\nhuman: hello\nai: hi there"
)

_GOLDEN_INTENT = (
    "Classify the intent of the LATEST user message into one of: analysis, planning, "
    "recommendation, general. Use the recent conversation for context if the latest "
    "message alone is ambiguous.\n\n"
    "Use analysis for questions answered from data the user already has — what they "
    "spent, a breakdown of where their money went, listing their transactions, or how "
    "much they could save per month based on their own income. Use planning only when "
    "the user wants to build a new budget or spending plan, which starts a "
    "questionnaire.\n\n"
    "If the message describes, asks for help with, or seeks a method for an illegal "
    "or harmful act (e.g. theft, fraud, money laundering, violence, evading law "
    'enforcement) — even if it uses financial vocabulary like "bank" or "money" — '
    "classify it as general, never as planning, analysis, or recommendation.\n"
    "Latest user message: How much did I spend?\n"
    "Respond with ONLY the intent word for the latest message.\n"
)

_GOLDEN_INTENT_WITH_HISTORY = (
    "Classify the intent of the LATEST user message into one of: analysis, planning, "
    "recommendation, general. Use the recent conversation for context if the latest "
    "message alone is ambiguous.\n\n"
    "Use analysis for questions answered from data the user already has — what they "
    "spent, a breakdown of where their money went, listing their transactions, or how "
    "much they could save per month based on their own income. Use planning only when "
    "the user wants to build a new budget or spending plan, which starts a "
    "questionnaire.\n\n"
    "If the message describes, asks for help with, or seeks a method for an illegal "
    "or harmful act (e.g. theft, fraud, money laundering, violence, evading law "
    'enforcement) — even if it uses financial vocabulary like "bank" or "money" — '
    "classify it as general, never as planning, analysis, or recommendation.\n"
    "Recent conversation:\n"
    "human: what did i spend on the most last month?\n"
    "\n"
    "Latest user message: what about this month ?\n"
    "Respond with ONLY the intent word for the latest message.\n"
)


def test_summary_prompt_matches_hardcoded_output():
    """US2 acceptance #1 — summarization template is byte-for-byte the old inline prompt."""
    rendered = get_summary_prompt().render(turns=["human: hello", "ai: hi there"])
    assert rendered == _GOLDEN_SUMMARY


def test_intent_classification_prompt_matches_hardcoded_output():
    """US2 acceptance #2 — classification template matches and still names the fixed labels."""
    rendered = get_intent_classification_prompt().render(
        message="How much did I spend?", history=None
    )
    assert rendered == _GOLDEN_INTENT
    # The fixed intent-label set must remain present verbatim in the rendered text.
    assert "analysis, planning, recommendation, general" in rendered
    # The illegal/harmful-act routing guard must survive future wording edits to
    # this template — a bank-robbery request must never classify as "planning".
    assert "illegal or harmful act" in rendered


def test_intent_classification_prompt_includes_history_when_present():
    rendered = get_intent_classification_prompt().render(
        message="what about this month ?",
        history="human: what did i spend on the most last month?",
    )
    assert rendered == _GOLDEN_INTENT_WITH_HISTORY
