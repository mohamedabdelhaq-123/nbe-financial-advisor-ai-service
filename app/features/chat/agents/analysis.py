"""Analysis agent — reads backend DB and provides grounded spending answers."""

from langchain_core.messages import AIMessage

from app.core.config import settings
from app.features.chat.guards import with_disclaimer
from app.features.chat.state import ConversationState
from collections.abc import Sequence


async def analysis_node(state: ConversationState) -> dict:
    try:
        from sqlalchemy import select

        from app.backend_db import get_backend_session
        from app.backend_db.models import Transaction

        user_id = state["user_context"].get("user_id")
        if not user_id:
            return {
                "messages": [AIMessage(content="I don't have a user context to analyse.")],
                "message_references": [],
            }

        transactions: Sequence[Transaction] = []
        async for session in get_backend_session():
            result = await session.execute(
                select(Transaction).where(Transaction.user_id == str(user_id)).limit(10)
            )
            transactions = result.scalars().all()

        if not transactions:
            return {
                "messages": [
                    AIMessage(content="I don't have that data yet. No transactions found."),
                ],
                "message_references": [],
            }

        references = []
        lines = []
        for txn in transactions:
            ref = {"table": "transactions", "id": getattr(txn, "id", None)}
            references.append(ref)
            amount = getattr(txn, "amount", 0)
            desc = getattr(txn, "merchant_raw", "unknown")
            category = getattr(txn, "category", "uncategorized")
            lines.append(f"- {desc} ({category}): {amount}")

        if settings.use_mock_llm:
            reply = "Based on your transactions:\n" + "\n".join(lines)
        else:
            from app.core.llm import get_chat_model

            data_context = "\n".join(lines)
            prompt = (
                f"User asked about their spending. Here are their transactions:\n{data_context}\n"
                "Provide a grounded summary. Cite specific figures only from this data. "
                "State 'I don't have that data yet' for anything not covered."
            )
            llm_result = await get_chat_model().ainvoke(prompt)
            raw_content = (
                llm_result.content
                if isinstance(llm_result.content, str)
                else str(llm_result.content)
            )
            reply = raw_content

        return {
            "messages": [AIMessage(content=with_disclaimer(reply))],
            "message_references": references,
        }
    except Exception:
        return {
            "messages": [
                AIMessage(
                    content=with_disclaimer("I don't have that data yet. Backend is unavailable.")
                ),
            ],
            "message_references": [],
        }
