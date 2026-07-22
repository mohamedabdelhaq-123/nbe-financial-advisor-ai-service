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
    # If we are already mid-planning (questions asked but plan not yet complete),
    # preserve the routing — the new message is an answer to the questionnaire,
    # not a fresh intent signal.
    if state.get("stage") == "planning" and state.get("questions_asked", 0) > 0:
        return {"intent": "planning"}

    last_msg = state["messages"][-1] if state["messages"] else None
    text = ""
    if last_msg and hasattr(last_msg, "content") and isinstance(last_msg.content, str):
        text = last_msg.content

    if settings.chat_model.use_mock:
        intent = classify_intent(text)
    else:
        from app.core.llm import get_chat_model
        from app.features.chat.prompts import get_intent_classification_prompt

        prompt = get_intent_classification_prompt().render(message=text)
        result = await get_chat_model().ainvoke(prompt)
        raw = result.content if isinstance(result.content, str) else str(result.content)
        classified = raw.strip().lower()
        intent = classified if classified in _INTENT_KEYWORDS else "general"

    return {"intent": intent}
