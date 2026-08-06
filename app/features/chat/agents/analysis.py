"""Analysis agent — reads backend DB and provides grounded spending answers."""

from langchain_core.messages import AIMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.features.chat.guards import with_disclaimer
from app.features.chat.schemas import Reference
from app.features.chat.state import ConversationState

logger = get_logger(__name__)


async def analysis_node(state: ConversationState) -> dict:
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.backend_db import get_backend_session
        from app.backend_db.models import Transaction

        user_id = state.get("user_id")
        if not user_id:
            return {
                "messages": [AIMessage(content="I don't have a user context to analyse.")],
                "message_references": [],
            }

        # `category` is a relationship (FK to categories), not a plain column.
        # Under AsyncSession, an implicit lazy load can't be triggered by plain
        # attribute access at all — it needs a greenlet context and raises
        # MissingGreenlet — so it must be eager-loaded as part of this query
        # (selectinload), not touched lazily later regardless of session state.
        references: list[Reference] = []
        lines: list[str] = []
        async for session in get_backend_session():
            result = await session.execute(
                select(Transaction)
                .where(Transaction.user_id == user_id)
                .options(selectinload(Transaction.category))
                .limit(10)
            )
            transactions = result.scalars().all()

            for txn in transactions:
                references.append(Reference(target_type="transaction", target_id=str(txn.id)))
                amount = getattr(txn, "amount", 0)
                desc = getattr(txn, "merchant_raw", "unknown")
                category = txn.category.name if txn.category else "uncategorized"
                lines.append(f"- {desc} ({category}): {amount}")

        if not lines:
            return {
                "messages": [
                    AIMessage(content="I don't have that data yet. No transactions found."),
                ],
                "message_references": [],
            }

        if settings.chat_model.use_mock:
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
        logger.exception("analysis_node_failed", user_id=str(state.get("user_id")))
        return {
            "messages": [
                AIMessage(
                    content=with_disclaimer("I don't have that data yet. Backend is unavailable.")
                ),
            ],
            "message_references": [],
        }
