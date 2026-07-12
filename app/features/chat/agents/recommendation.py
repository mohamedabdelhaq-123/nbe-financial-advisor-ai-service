"""Recommendation agent — matches user needs to products."""

from langchain_core.messages import AIMessage

from app.features.chat.state import ConversationState


async def recommendation_node(state: ConversationState) -> dict:
    try:
        from app.core.db import get_own_session
        from app.features.recommendations.service import match

        last_msg = state["messages"][-1] if state["messages"] else None
        query = ""
        if last_msg and hasattr(last_msg, "content"):
            content = last_msg.content
            query = content if isinstance(content, str) else str(content)
        user_id = state["user_context"].get("user_id", 0)

        product_matches = []
        async for session in get_own_session():
            product_matches = await match(
                session=session,
                user_id=int(user_id) if user_id else 0,
                query=query,
                top_k=3,
            )

        if not product_matches:
            return {
                "messages": [AIMessage(content="No matching products found right now.")],
                "message_references": [],
            }

        lines = [f"- {m.product_name} (similarity: {m.similarity:.2f})" for m in product_matches]
        reply = "Here are some products that might suit you:\n" + "\n".join(lines)
        refs = [
            {"table": "products", "id": m.product_id, "similarity": m.similarity}
            for m in product_matches
        ]
        return {
            "messages": [AIMessage(content=reply)],
            "message_references": refs,
        }
    except ImportError:
        return {
            "messages": [AIMessage(content="Recommendations are being set up.")],
            "message_references": [],
        }
