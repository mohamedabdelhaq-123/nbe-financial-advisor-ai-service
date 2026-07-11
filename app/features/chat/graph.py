"""LangGraph graph — compiles the conversation pipeline."""

from langgraph.graph import END, StateGraph

from app.features.chat.agents.analysis import analysis_node
from app.features.chat.agents.maestro import maestro_node
from app.features.chat.agents.planner import planner_node
from app.features.chat.agents.recommendation import recommendation_node
from app.features.chat.state import ConversationState
from app.features.chat.summarize import needs_summary, summarize_node


def _route_intent(state: ConversationState) -> str:
    intent = state.get("intent", "general")
    routing = {
        "analysis": "analysis",
        "planning": "planner",
        "recommendation": "recommendation",
    }
    return routing.get(intent, "general")


def _maybe_summarize(state: ConversationState) -> str:
    if needs_summary(state):
        return "summarize"
    return "maestro"


async def _general_node(state: ConversationState) -> dict:
    from langchain_core.messages import AIMessage

    from app.core.config import settings

    last_msg = state["messages"][-1] if state["messages"] else None
    text = last_msg.content if last_msg and hasattr(last_msg, "content") else ""

    if settings.use_mock_llm:
        reply = f"Thank you for your message. You said: '{text[:100]}'. How can I help you further?"
    else:
        from app.core.llm import get_chat_model

        result = await get_chat_model().ainvoke(text)
        reply = result.content if isinstance(result.content, str) else str(result.content)

    return {"messages": [AIMessage(content=reply)]}


def build_graph(checkpointer=None):
    graph = StateGraph(ConversationState)

    graph.add_node("summarize", summarize_node)
    graph.add_node("maestro", maestro_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("planner", planner_node)
    graph.add_node("recommendation", recommendation_node)
    graph.add_node("general", _general_node)

    graph.set_entry_point("summarize")
    edges_map = {"summarize": "summarize", "maestro": "maestro"}
    graph.add_conditional_edges("summarize", _maybe_summarize, edges_map)
    graph.add_conditional_edges(
        "maestro",
        _route_intent,
        {
            "analysis": "analysis",
            "planner": "planner",
            "recommendation": "recommendation",
            "general": "general",
        },
    )
    graph.add_edge("analysis", END)
    graph.add_edge("planner", END)
    graph.add_edge("recommendation", END)
    graph.add_edge("general", END)

    return graph.compile(checkpointer=checkpointer)
