"""Recommendation agent — matches user needs to products."""

from langchain_core.messages import AIMessage

from app.features.chat.state import ConversationState


async def recommendation_node(state: ConversationState) -> dict:
    try:
        from app.features.recommendations.service import match

        last_msg = state["messages"][-1] if state["messages"] else None
        query = last_msg.content if last_msg and hasattr(last_msg, "content") else ""
        user_id = state["user_context"].get("user_id", 0)

        product_matches = await match(query=query, user_id=user_id, top_k=3)

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
