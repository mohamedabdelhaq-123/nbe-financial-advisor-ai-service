"""LangGraph graph — compiles the conversation pipeline."""

from langgraph.graph import END, StateGraph

from app.features.chat.agents.analysis import analysis_node
from app.features.chat.agents.investment import investment_plan_node
from app.features.chat.agents.maestro import maestro_node
from app.features.chat.agents.planner import planner_ask_node, validate_answer_node
from app.features.chat.agents.recommendation import recommendation_node
from app.features.chat.guards import GENERAL_NODE_SYSTEM_PROMPT
from app.features.chat.routing import DEFAULT_CLARIFICATION, ROUTES_BY_NAME
from app.features.chat.state import ConversationState
from app.features.chat.summarize import needs_summary, summarize_node


def _route_intent(state: ConversationState) -> str:
    outcome = state.get("routing_outcome", "route")
    if outcome == "refuse":
        return "refused"
    if outcome == "clarify":
        return "clarify"
    spec = ROUTES_BY_NAME.get(state.get("intent", "general"))
    return spec.graph_node if spec else "general"


def _route_planner_ask(state: ConversationState) -> str:
    # planner_ask either paused on interrupt() to ask a question (in which
    # case the resumed answer needs validating) or ran generate_plan to
    # completion with no question left to ask.
    return "done" if state.get("stage") == "plan_complete" else "validate"


def _route_investment_plan(state: ConversationState) -> str:
    # "escaped": the resumed message didn't attempt to answer anything
    # investment_plan_node asked (agents/investment.py's
    # InvestmentAnswerExtraction.is_escape) — hand this same turn to
    # Maestro for a fresh routing decision instead of ending the turn on a
    # forced non-answer. investment_answers is untouched either way, so
    # re-entering investment_planning later resumes where this left off.
    if state.get("stage") == "investment_plan_escaped":
        return "escaped"
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


async def _refused_node(state: ConversationState) -> dict:
    from langchain_core.messages import AIMessage

    reply = (
        "I'm the NBE Financial Advisor assistant, so I can only help with your "
        "spending, budgeting, curated investment planning, and banking questions. "
        "Let me know if there's "
        "something along those lines I can help with."
    )
    return {
        "messages": [AIMessage(content=reply)],
        "intent": "refused",
        "routing_outcome": "refuse",
    }


async def _clarify_node(state: ConversationState) -> dict:
    """Ask one concise question instead of guessing a low-confidence route."""

    from langchain_core.messages import AIMessage

    question = state.get("routing_clarification") or DEFAULT_CLARIFICATION
    return {
        "messages": [AIMessage(content=question)],
        "intent": "clarify",
        "routing_outcome": "clarify",
    }


async def _general_node(state: ConversationState) -> dict:
    from langchain_core.messages import AIMessage, SystemMessage

    from app.core.config import settings

    last_msg = state["messages"][-1] if state["messages"] else None
    text = last_msg.content if last_msg and hasattr(last_msg, "content") else ""

    if settings.chat_model.use_mock:
        reply = f"Thank you for your message. You said: '{text[:100]}'. How can I help you further?"
    else:
        from app.core.llm import get_chat_model

        # Full history, same pattern as analysis.py's _agentic_analysis — a
        # reflective follow-up about a prior turn (e.g. "why did you choose
        # that?" after a recommendation reply) needs the actual prior
        # messages to answer from, not just its own latest line in
        # isolation. Safe to include past tool-call turns unfiltered: this
        # exact "plain call sees prior AIMessage/ToolMessage tool-call pairs
        # in its input, tools unbound for this call" shape is already
        # exercised by analysis.py's own MAX_TOOL_ITERATIONS fallback path.
        #
        # streaming=True: this node's output goes straight to the user, and
        # `general` is in service.py's _LEAF_NODES, so its tokens are forwarded
        # as they're produced instead of arriving as one chunk at the end.
        result = await get_chat_model(streaming=True).ainvoke(
            [SystemMessage(content=GENERAL_NODE_SYSTEM_PROMPT), *state["messages"]]
        )
        reply = result.content if isinstance(result.content, str) else str(result.content)

    return {"messages": [AIMessage(content=reply)]}


def build_graph(checkpointer=None):
    graph = StateGraph(ConversationState)

    graph.add_node("refused", _refused_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("maestro", maestro_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("planner_ask", planner_ask_node)
    graph.add_node("validate_answer", validate_answer_node)
    graph.add_node("recommendation", recommendation_node)
    graph.add_node("investment_plan", investment_plan_node)
    graph.add_node("general", _general_node)

    graph.set_entry_point("summarize")
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
            "refused": "refused",
            "clarify": "clarify",
        },
    )
    graph.add_conditional_edges(
        "planner_ask", _route_planner_ask, {"validate": "validate_answer", "done": END}
    )
    graph.add_edge("validate_answer", "planner_ask")
    graph.add_conditional_edges(
        "investment_plan",
        _route_investment_plan,
        {"continue": "investment_plan", "done": END, "escaped": "maestro"},
    )
    graph.add_edge("analysis", END)
    graph.add_edge("recommendation", END)
    graph.add_edge("general", END)
    graph.add_edge("refused", END)
    graph.add_edge("clarify", END)

    return graph.compile(checkpointer=checkpointer)
