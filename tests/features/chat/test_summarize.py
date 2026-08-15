"""US1 Unit test: Conversation summarisation and trimming."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.features.chat.summarize import format_turns, needs_summary, summarize_node, trim_for_llm


def _make_messages(n: int) -> list:
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append(HumanMessage(content=f"message {i}"))
        else:
            msgs.append(AIMessage(content=f"reply {i}"))
    return msgs


def test_needs_summary_below_threshold():
    state = {"messages": _make_messages(39)}
    assert not needs_summary(state)


def test_needs_summary_at_threshold():
    state = {"messages": _make_messages(41)}
    assert needs_summary(state)


@pytest.mark.asyncio
async def test_summarize_node_compresses_messages():
    old_messages = _make_messages(41)
    state = {"messages": old_messages}
    result = await summarize_node(state)
    assert "messages" in result
    assert len(result["messages"]) < len(old_messages)
    summary_msgs = [m for m in result["messages"] if isinstance(m, SystemMessage)]
    assert len(summary_msgs) >= 1


def test_trim_for_llm_keeps_limit():
    messages = _make_messages(50)
    trimmed = trim_for_llm(messages)
    assert len(trimmed) <= 20


def test_trim_for_llm_keeps_latest():
    messages = _make_messages(50)
    trimmed = trim_for_llm(messages)
    assert trimmed[-1].content == "reply 49"


def test_format_turns_empty_history():
    assert format_turns([]) == ""


def test_format_turns_includes_role_and_content():
    messages = _make_messages(2)
    digest = format_turns(messages, limit=4)
    assert "human: message 0" in digest
    assert "ai: reply 1" in digest


def test_format_turns_respects_limit():
    messages = _make_messages(10)
    digest = format_turns(messages, limit=2)
    lines = digest.split("\n")
    assert len(lines) == 2
    assert "reply 9" in lines[-1]
    assert "message 8" in lines[0]


def test_format_turns_truncates_long_content():
    messages = [HumanMessage(content="x" * 500)]
    digest = format_turns(messages, limit=4)
    assert len(digest) <= len("human: ") + 200
