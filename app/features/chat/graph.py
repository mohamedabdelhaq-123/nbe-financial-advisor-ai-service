"""LangGraph graph — compiles the conversation pipeline."""

from langgraph.graph import END, StateGraph

from app.features.chat.agents.analysis import analysis_node
from app.features.chat.agents.investment import investment_plan_node
from app.features.chat.agents.maestro import maestro_node
from app.features.chat.agents.planner import planner_ask_node, validate_answer_node
from app.features.chat.agents.recommendation import recommendation_node
from app.features.chat.guards import GENERAL_NODE_SYSTEM_PROMPT
from app.features.chat.scope_guard import build_scope_check_text, check_scope
from app.features.chat.state import ConversationState
from app.features.chat.summarize import needs_summary, summarize_node


def _route_intent(state: ConversationState) -> str:
    intent = state.get("intent", "general")
    routing = {
        "analysis": "analysis",
        "planning": "planner_ask",
        "recommendation": "recommendation",
        "investment_planning": "investment_plan",
    }
    return routing.get(intent, "general")


def _route_planner_ask(state: ConversationState) -> str:
    # planner_ask either paused on interrupt() to ask a question (in which
    # case the resumed answer needs validating) or ran generate_plan to
    # completion with no question left to ask.
    return "done" if state.get("stage") == "plan_complete" else "validate"


def _route_investment_plan(state: ConversationState) -> str:
    return (
        "done"
        if state.get("stage")
        in {"investment_plan_complete", "investment_plan_unpriced", "investment_plan_cancelled"}
        else "continue"
    )


def _maybe_summarize(state: ConversationState) -> str:
    if needs_summary(state):
        return "summarize"
    return "maestro"


async def _scope_guard_node(state: ConversationState) -> dict:
    # Mid-planning answers ("1200", "rent, groceries") are terse and
    # wouldn't classify confidently either way on their own — same
    # reasoning maestro_node already uses to skip its own classification
    # for these, applied here for the same reason.
    if (
        state.get("stage") == "planning" and state.get("questions_asked", 0) > 0
    ) or state.get("stage") == "investment_planning":
        return {"in_scope": True}

    if state.get("stage") == "investment_plan_complete":
        from app.features.chat.agents.investment import parse_instrument_selection

        last_msg = state["messages"][-1] if state["messages"] else None
        text = getattr(last_msg, "content", "")
        if isinstance(text, str) and parse_instrument_selection(
            text,
            state.get("investment_context"),
            state.get("investment_answers"),
        ):
            return {"in_scope": True}

    text = build_scope_check_text(state["messages"], last_intent=state.get("intent"))

    result = await check_scope(text)
    return {"in_scope": result.in_scope}


def _route_scope(state: ConversationState) -> str:
    # Defaults open (True) if somehow unset — check_scope() itself already
    # fails open (disabled guard, or the classifier erroring), so this
    # default only matters if the node above never ran at all.
    return "in_scope" if state.get("in_scope", True) else "refused"


async def _refused_node(state: ConversationState) -> dict:
    from langchain_core.messages import AIMessage

    reply = (
        "I'm the NBE Financial Advisor assistant, so I can only help with your "
        "spending, budgeting, curated investment planning, and banking questions. "
        "Let me know if there's "
        "something along those lines I can help with."
    )
    # Maestro never runs on a blocked turn (scope_guard rejects before
    # routing), so state["intent"] would otherwise still hold whatever it
    # was from the last turn Maestro DID run — stale and possibly a task
    # intent, which build_scope_check_text would wrongly trust as context
    # on the next turn. "refused" isn't in _TASK_INTENTS, so it's excluded
    # the same way a "general" reply is.
    return {"messages": [AIMessage(content=reply)], "intent": "refused"}


async def _general_node(state: ConversationState) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from app.core.config import settings

    last_msg = state["messages"][-1] if state["messages"] else None
    text = last_msg.content if last_msg and hasattr(last_msg, "content") else ""

    if settings.chat_model.use_mock:
        reply = f"Thank you for your message. You said: '{text[:100]}'. How can I help you further?"
    else:
        from app.core.llm import get_chat_model

        # streaming=True: this node's output goes straight to the user, and
        # `general` is in service.py's _LEAF_NODES, so its tokens are forwarded
        # as they're produced instead of arriving as one chunk at the end.
        result = await get_chat_model(streaming=True).ainvoke(
            [SystemMessage(content=GENERAL_NODE_SYSTEM_PROMPT), HumanMessage(content=text)]
        )
        reply = result.content if isinstance(result.content, str) else str(result.content)

    return {"messages": [AIMessage(content=reply)]}


def build_graph(checkpointer=None):
    graph = StateGraph(ConversationState)

    graph.add_node("scope_guard", _scope_guard_node)
    graph.add_node("refused", _refused_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("maestro", maestro_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("planner_ask", planner_ask_node)
    graph.add_node("validate_answer", validate_answer_node)
    graph.add_node("recommendation", recommendation_node)
    graph.add_node("investment_plan", investment_plan_node)
    graph.add_node("general", _general_node)

    graph.set_entry_point("scope_guard")
    graph.add_conditional_edges(
        "scope_guard", _route_scope, {"in_scope": "summarize", "refused": "refused"}
    )
    edges_map = {"summarize": "summarize", "maestro": "maestro"}
    graph.add_conditional_edges("summarize", _maybe_summarize, edges_map)
    graph.add_conditional_edges(
        "maestro",
        _route_intent,
        {
            "analysis": "analysis",
            "planner_ask": "planner_ask",
            "recommendation": "recommendation",
            "investment_plan": "investment_plan",
            "general": "general",
        },
    )
    graph.add_conditional_edges(
        "planner_ask", _route_planner_ask, {"validate": "validate_answer", "done": END}
    )
    graph.add_edge("validate_answer", "planner_ask")
    graph.add_conditional_edges(
        "investment_plan",
        _route_investment_plan,
        {"continue": "investment_plan", "done": END},
    )
    graph.add_edge("analysis", END)
    graph.add_edge("recommendation", END)
    graph.add_edge("general", END)
    graph.add_edge("refused", END)

    return graph.compile(checkpointer=checkpointer)
