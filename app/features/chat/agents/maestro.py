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
    logger.warning("intent_classification_unparsed", raw=raw, fallback=keyword_intent)
    return keyword_intent


async def _planner_context_update(state: ConversationState) -> dict:
    """Assembles planner_context once per session (Pipeline.md §3: Maestro
    assembles user context before delegating to a sub-agent) and caches it
    in state — never re-derives once set. Deriving it here rather than in
    planner_ask_node also sidesteps a real LangGraph interrupt() gotcha: a
    node that calls interrupt() re-executes from its own start on every
    resume, so anything before the interrupt() call would otherwise re-run
    (and re-hit the DB) on every single answer, not just once per session.
    Maestro doesn't run again during the interrupt loop at all, so this is
    the one place a single derivation actually sticks."""
    if state.get("planner_context") is not None:
        return {}
    from app.features.plan.context import derive_planner_context

    context = await derive_planner_context(state["user_id"])
    return {"planner_context": context}


async def maestro_node(state: ConversationState) -> dict:
    # If we are already mid-planning (questions asked but plan not yet complete),
    # preserve the routing — the new message is an answer to the questionnaire,
    # not a fresh intent signal.
    if state.get("stage") == "planning" and state.get("questions_asked", 0) > 0:
        return {"intent": "planning", **await _planner_context_update(state)}

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
        intent = _parse_llm_intent(raw, text)

    if intent == "planning":
        was_first_turn = state.get("planner_context") is None
        extra = await _planner_context_update(state)
        if was_first_turn:
            from app.features.plan.service import extract_stated_goal

            stated_goal = await extract_stated_goal(text)
            if stated_goal:
                extra["stated_savings_goal"] = stated_goal
        return {"intent": intent, **extra}
    return {"intent": intent}
