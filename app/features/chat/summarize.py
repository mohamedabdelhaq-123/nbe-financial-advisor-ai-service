"""Conversation summarisation and context trimming."""

from langchain_core.messages import SystemMessage

from app.core.config import settings
from app.features.chat.state import ConversationState

SUMMARY_THRESHOLD = 40
TRIM_LIMIT = 20


def needs_summary(state: ConversationState) -> bool:
    return len(state["messages"]) > SUMMARY_THRESHOLD


async def summarize_node(state: ConversationState) -> dict:
    messages = state["messages"]
    old = messages[:-TRIM_LIMIT]
    if not old:
        return {"messages": messages}

    if settings.chat_model.use_mock:
        summary_text = f"Summary of {len(old)} earlier messages in the conversation."
    else:
        from app.core.llm import get_chat_model
        from app.features.chat.prompts import get_summary_prompt

        turns = [f"{m.type}: {m.content[:200]}" for m in old if hasattr(m, "content")]
        prompt = get_summary_prompt().render(turns=turns)
        result = await get_chat_model().ainvoke(prompt)
        summary_text = result.content if isinstance(result.content, str) else str(result.content)

    summary_msg = SystemMessage(content=summary_text)
    remaining = messages[len(old) :]
    return {"messages": [summary_msg] + remaining}


def trim_for_llm(messages: list) -> list:
    if len(messages) <= TRIM_LIMIT:
        return messages
    return messages[-TRIM_LIMIT:]
