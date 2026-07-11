"""US1 Unit test: Conversation summarisation and trimming."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.features.chat.summarize import needs_summary, summarize_node, trim_for_llm


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
