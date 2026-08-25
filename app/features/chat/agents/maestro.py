"""Maestro orchestrator — classifies user intent and routes to sub-agents."""

from app.core.config import settings
from app.core.logging import get_logger
from app.features.chat.state import ConversationState

logger = get_logger(__name__)

# Includes "general", not just the three task agents: _parse_llm_intent below
# must trust a clean "general" reply as-is. Treating it as unparsed instead
# falls through to classify_intent(message) — a blind keyword scan of the
# ORIGINAL message with no awareness of why the LLM picked "general" (e.g.
# the illegal/harmful-act routing instruction in intent_classification.jinja2)
# — which is exactly how "i want a plan to rob a bank" got silently routed
# back to "planning" by the literal word "plan" in the message.
_VALID_INTENTS = ("planning", "analysis", "recommendation", "general")

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
        # Savings-projection phrasings. Deliberately multi-word: this dict is
        # scanned in insertion order and returns on the first hit, so a bare
        # "saving" here would swallow "which savings account is best" before
        # the recommendation list below ever gets a look.
        "how much should i save",
        "how much can i save",
        "save per month",
        "saving per month",
        "savings projection",
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


def classify_intent(message: str, history: str = "") -> str:
    lower = message.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return intent
    # The bare message alone carries no keyword signal (a short, elliptical
    # follow-up like "what about this month?") — fall back to scanning
    # recent history so mock mode/tests can exercise the same
    # context-disambiguation the real LLM prompt does with `history` below.
    if history:
        lower_history = history.lower()
        for intent, keywords in _INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in lower_history:
                    return intent
    return "general"


def _parse_llm_intent(raw: str, message: str) -> str:
    """Parses the classifier LLM's freeform reply into one of the known
    intents (see _VALID_INTENTS above for why "general" must be included).

    Beyond that, the prompt asks for a single bare word, but small/free
    models routinely wrap it in punctuation or extra words. Tolerates that
    by first checking for a clean match, then a loose (substring) match,
    then falling back to the same keyword matcher mock mode uses, logging
    whenever the LLM's reply wasn't clean so a classification regression
    shows up in logs instead of silently routing everything to the
    no-context fallback."""
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

    from app.features.chat.summarize import format_turns

    history = format_turns(state["messages"][:-1], limit=4)

    if settings.chat_model.use_mock:
        intent = classify_intent(text, history=history)
    else:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.core.llm import get_chat_model
        from app.features.chat.prompts import (
            get_intent_classification_human_prompt,
            get_intent_classification_system_prompt,
        )

        system_prompt = get_intent_classification_system_prompt().render()
        human_prompt = get_intent_classification_human_prompt().render(
            message=text, history=history or None
        )
        result = await get_chat_model().ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
        )
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
