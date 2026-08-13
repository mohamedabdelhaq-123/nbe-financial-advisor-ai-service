"""Analysis agent — reads backend DB and provides grounded spending answers.

Two entirely separate paths, matching every other node's use_mock branch:

* Mock mode (tests/CI, AI_SERVICE_CHAT_MODEL__USE_MOCK=1): the original fixed
  query — last 10 transactions, no filters, templated reply. Left untouched
  so the existing unit tests (tests/features/chat/test_analysis_agent.py),
  which monkeypatch `get_backend_session` and assert on this exact shape,
  keep passing.
* Real model: a bounded tool-calling loop (see MAX_TOOL_ITERATIONS) using the
  get_transactions/compute_aggregate tools from app.tools.transactions. The
  model chooses filters and calls compute_aggregate for any math instead of
  the old "hand the LLM 10 raw rows and hope it sums correctly" approach.
"""

import datetime
import json
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.features.chat.schemas import Reference
from app.features.chat.state import ConversationState

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 3

ANALYSIS_SYSTEM_PROMPT_TEMPLATE = (
    "You are the NBE Financial Advisor assistant's analysis agent. Answer "
    "questions about the user's own spending, income, and transactions using "
    "ONLY the get_transactions and compute_aggregate tools — never state a "
    "figure, total, or calculation you didn't get from a tool result.\n\n"
    "Always use compute_aggregate for any total, average, count, minimum, or "
    "maximum — never add up or average get_transactions rows yourself. Prefer "
    "the `flow` argument (\"income\"/\"expense\") for plain spending/income "
    "questions; use `transaction_type` only for precise single-type requests "
    "like \"just my fees\".\n\n"
    "If a tool call returns no matching data, say so plainly (e.g. \"I don't "
    "have that data yet\") rather than guessing. If the request is ambiguous "
    "(e.g. no date range given), pick a reasonable default and state what you "
    "assumed. Today's date is {today}."
)


async def analysis_node(state: ConversationState) -> dict:
    user_id = state.get("user_id")
    if not user_id:
        return {
            "messages": [AIMessage(content="I don't have a user context to analyse.")],
            "message_references": [],
        }

    if settings.chat_model.use_mock:
        return await _mock_analysis(user_id)
    return await _agentic_analysis(state, user_id)


async def _mock_analysis(user_id) -> dict:
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.backend_db import get_backend_session
        from app.backend_db.models import Transaction

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

        reply = "Based on your transactions:\n" + "\n".join(lines)
        return {
            "messages": [AIMessage(content=reply)],
            "message_references": references,
        }
    except Exception:
        logger.exception("analysis_node_mock_failed", user_id=str(user_id))
        return {
            "messages": [
                AIMessage(content="I don't have that data yet. Backend is unavailable."),
            ],
            "message_references": [],
        }


async def _agentic_analysis(state: ConversationState, user_id) -> dict:
    try:
        from app.core.llm import get_chat_model
        from app.tools.transactions import make_transaction_tools

        tools = make_transaction_tools(user_id)
        tools_by_name = {t.name: t for t in tools}
        # streaming=True so the grounded answer reaches the user token by token
        # (`analysis` is one of service.py's _LEAF_NODES). bind_tools() carries
        # the setting over to the tool-calling loop as well; the intermediate
        # tool-call turns stream too, but those chunks carry empty `content`
        # and service.py already skips empty content, so nothing leaks from
        # them into the user's reply.
        base_model = get_chat_model(streaming=True)
        model_with_tools = base_model.bind_tools(tools)

        system = SystemMessage(
            content=ANALYSIS_SYSTEM_PROMPT_TEMPLATE.format(
                today=datetime.date.today().isoformat()
            )
        )
        working: list[AnyMessage] = [system, *state["messages"]]
        produced: list[AnyMessage] = []
        seen_transaction_ids: set[str] = set()

        final_ai_message = None
        for _ in range(MAX_TOOL_ITERATIONS):
            ai_message = await model_with_tools.ainvoke(working)
            working.append(ai_message)

            tool_calls = getattr(ai_message, "tool_calls", None) or []
            if not tool_calls:
                final_ai_message = ai_message
                break

            produced.append(ai_message)
            for call in tool_calls:
                tool_fn = tools_by_name.get(call["name"])
                tool_result: dict[str, Any]
                if tool_fn is None:
                    tool_result = {"error": f"unknown tool {call['name']}"}
                else:
                    try:
                        tool_result = await tool_fn.ainvoke(call["args"])
                    except Exception as exc:
                        # Bad arguments (e.g. a small model passing the string
                        # "none" instead of omitting an optional field) must
                        # come back as an observation the model can react to
                        # and retry within the remaining iterations — not
                        # escape the loop and land on the generic backend-
                        # unavailable fallback below, which would be
                        # misleading here since the DB was never touched.
                        logger.warning(
                            "analysis_tool_call_invalid_args",
                            tool=call["name"],
                            args=call["args"],
                            error=str(exc),
                        )
                        tool_result = {"error": f"Invalid arguments: {exc}"}
                    if call["name"] == "get_transactions" and isinstance(tool_result, dict):
                        for row in tool_result.get("transactions", []):
                            seen_transaction_ids.add(row["id"])

                tool_message = ToolMessage(
                    content=json.dumps(tool_result, default=str),
                    tool_call_id=call["id"],
                )
                working.append(tool_message)
                produced.append(tool_message)

        if final_ai_message is None:
            # Exhausted MAX_TOOL_ITERATIONS still requesting tools — force a
            # plain answer with no tools bound so the user's turn never ends
            # on a dangling tool call.
            final_ai_message = await base_model.ainvoke(working)

        raw_content = (
            final_ai_message.content
            if isinstance(final_ai_message.content, str)
            else str(final_ai_message.content)
        )
        produced.append(AIMessage(content=raw_content))

        references = [
            Reference(target_type="transaction", target_id=tid) for tid in seen_transaction_ids
        ]
        return {"messages": produced, "message_references": references}
    except Exception:
        logger.exception("analysis_node_agentic_failed", user_id=str(user_id))
        return {
            "messages": [
                AIMessage(content="I don't have that data yet. Backend is unavailable."),
            ],
            "message_references": [],
        }
