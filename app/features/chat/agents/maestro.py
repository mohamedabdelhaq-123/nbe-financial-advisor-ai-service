"""Maestro orchestrator — classifies user intent and routes to sub-agents."""

from app.core.config import settings
from app.core.logging import get_logger
from app.features.chat.state import ConversationState

logger = get_logger(__name__)

_VALID_INTENTS = ("planning", "analysis", "recommendation")

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


def _parse_llm_intent(raw: str, message: str) -> str:
    """Parses the classifier LLM's freeform reply into one of the known
    intents. The prompt asks for a single bare word, but small/free models
    routinely wrap it in punctuation or extra words — an exact-match check
    silently dropped those replies to "general" (no data access) instead of
    the correct agent. Tolerates that by first checking for a clean match,
    then a loose (substring) match, then falling back to the same keyword
    matcher mock mode uses, logging whenever the LLM's reply wasn't clean so
    a classification regression shows up in logs instead of silently
    routing everything to the no-context fallback."""
    cleaned = raw.strip().strip(".!?\"'").lower()
    if cleaned in _VALID_INTENTS:
        return cleaned

    for intent in _VALID_INTENTS:
        if intent in cleaned:
            logger.warning("intent_classification_loose_match", raw=raw, matched=intent)
            return intent

    keyword_intent = classify_intent(message)
    logger.warning(
        "intent_classification_unparsed", raw=raw, fallback=keyword_intent
    )
    return keyword_intent


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

        prompt = (
            "Classify the intent of this user message into one of: "
            "analysis, planning, recommendation, general.\n"
            f"Message: {text}\nRespond with ONLY the intent word."
        )
        result = await get_chat_model().ainvoke(prompt)
        raw = result.content if isinstance(result.content, str) else str(result.content)
        intent = _parse_llm_intent(raw, text)

    return {"intent": intent}
