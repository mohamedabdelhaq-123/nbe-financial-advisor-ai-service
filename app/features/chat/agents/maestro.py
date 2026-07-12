"""Maestro orchestrator — classifies user intent and routes to sub-agents."""

from app.core.config import settings
from app.features.chat.state import ConversationState

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "planning": [
        "budget",
        "plan",
        "spending plan",
        "allocate",
        "allocation",
        "planning",
    ],
    "analysis": [
        "spend",
        "spent",
        "expense",
        "expenses",
        "transaction",
        "transactions",
        "how much",
        "income",
        "salary",
        "balance",
        "statement",
    ],
    "recommendation": [
        "recommend",
        "product",
        "card",
        "account",
        "which card",
        "best card",
        "which account",
        "best account",
        "savings account",
        "credit card",
    ],
}


def classify_intent(message: str) -> str:
    lower = message.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return intent
    return "general"


async def maestro_node(state: ConversationState) -> dict:
    last_msg = state["messages"][-1] if state["messages"] else None
    text = ""
    if last_msg and hasattr(last_msg, "content") and isinstance(last_msg.content, str):
        text = last_msg.content

    if settings.use_mock_llm:
        intent = classify_intent(text)
    else:
        from app.core.llm import get_chat_model

        prompt = (
            "Classify the intent of this user message into one of: "
            "analysis, planning, recommendation, general.\n"
            f"Message: {text}\nRespond with ONLY the intent word."
        )
        result = await get_chat_model().ainvoke(prompt)
        raw = result.content if isinstance(result.content, str) else str(result.content)
        classified = raw.strip().lower()
        intent = classified if classified in _INTENT_KEYWORDS else "general"

    return {"intent": intent}
