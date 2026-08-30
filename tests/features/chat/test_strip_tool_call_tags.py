"""Unit tests for service.py's _strip_tool_call_tags — the defensive backstop
for OpenAI-compatible backends (e.g. the configured gpt-oss-20b:nitro route)
that emulate tool-calling as literal XML-ish text in `content` instead of
OpenAI's structured tool_calls field, which can otherwise leak the raw tag
into the streamed and persisted chat reply.
"""

import pytest

from app.features.chat.service import _strip_tool_call_tags


@pytest.mark.parametrize(
    "raw",
    [
        '<show_spending_breakdown date_from="2023-08-27" date_to="2026-08-27" />',
        '<show_transactions count="10"></show_transactions>',
        '<get_current_balance currency="EGP" />',
        '<compute_aggregate op="sum" flow="expense" />',
        '<find_similar_transactions query="coffee last week" top_k="5" />',
    ],
)
def test_strips_known_tool_tags(raw):
    text = f"You spent 205.51 EGP on food during the last three years.\n\n{raw}"
    assert (
        _strip_tool_call_tags(text)
        == "You spent 205.51 EGP on food during the last three years.\n\n"
    )


def test_leaves_plain_text_untouched():
    text = "You spent 205.51 EGP on food during the last three years."
    assert _strip_tool_call_tags(text) == text


def test_leaves_unrecognized_tag_untouched():
    # Only the known analysis-agent tool names are stripped — an unrelated
    # angle-bracket string in a reply (e.g. a user-quoted "<3" or HTML the
    # model echoed) must not be silently eaten.
    text = "Use <3 as a shortcut for love, not a tool tag."
    assert _strip_tool_call_tags(text) == text


def test_strips_multiple_tags_in_one_chunk():
    text = '<get_transactions limit="5" /><compute_aggregate op="sum" />done'
    assert _strip_tool_call_tags(text) == "done"
