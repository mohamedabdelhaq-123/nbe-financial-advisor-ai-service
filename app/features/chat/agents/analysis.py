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
import uuid
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.features.chat.schemas import (
    Reference,
    TransactionListItem,
    TransactionsListPayload,
    TransactionsListWidget,
)
from app.features.chat.state import ConversationState
from app.tools.transactions import flow_for_type

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 3

ANALYSIS_SYSTEM_PROMPT_TEMPLATE = (
    "You are the NBE Financial Advisor assistant's analysis agent. Answer "
    "questions about the user's own spending, income, and transactions using "
    "ONLY the get_transactions, compute_aggregate, and find_similar_transactions "
    "tools — never state a figure, total, or calculation you didn't get from a "
    "tool result.\n\n"
    "Always use compute_aggregate for any total, average, count, minimum, or "
    "maximum — never add up or average get_transactions or "
    "find_similar_transactions rows yourself. Prefer the `flow` argument "
    '("income"/"expense") for plain spending/income questions; use '
    '`transaction_type` only for precise single-type requests like "just my '
    'fees".\n\n'
    "Prefer get_transactions whenever the request has a clear filter (a "
    "category, a date range, income vs expense). Use find_similar_transactions "
    'only for a vague description with no such filter, like "that coffee place '
    'last week" or "my streaming subscriptions" — it ranks by similarity, not '
    "an exact match, so treat its results as candidates and say so if none look "
    "like a good fit rather than picking one anyway.\n\n"
    "You also have three display tools — show_spending_breakdown, "
    "show_transactions, and show_savings_projection — that render a chart, a "
    "list, or an interactive projection alongside your reply. Call the "
    "matching one IN ADDITION to answering when the user asks where their "
    "money went, to see their transactions, or about saving per month. For "
    "show_spending_breakdown and show_savings_projection, your written answer "
    "must still stand on its own: state the figures in prose too, never reply "
    "with only a display tool call or point at the widget instead of "
    "answering. For show_transactions, do the opposite: keep your prose to a "
    "brief one- or two-sentence summary (how many, the date range, the total) "
    "and never enumerate the individual transactions as a list or markdown "
    "table — the widget already shows every row, so repeating them in prose "
    "is pure duplication. If a display tool reports shown=false, explain its "
    "reason plainly rather than estimating the missing figure yourself.\n\n"
    "If the request describes, seeks help with, or asks for a method for an "
    "illegal or harmful act, decline plainly instead of answering, even if "
    "it references your own transaction data.\n\n"
    "If a tool call returns no matching data, say so plainly (e.g. \"I don't "
    'have that data yet") rather than guessing. If the request is ambiguous '
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
        return await _mock_analysis(state, user_id)
    return await _agentic_analysis(state, user_id)


def _mock_widget(transactions) -> TransactionsListWidget | None:
    """Builds a transactions_list widget from the rows the mock path already
    read, so a frontend running against AI_SERVICE_CHAT_MODEL__USE_MOCK=1 has a
    widget to render without a model or a real backend.

    Deliberately per-row tolerant: mock mode is also what the unit tests drive,
    and their fixtures are minimal stand-ins that carry only the fields the
    assertion under test needs. A row missing a real UUID, a currency, or a
    date is skipped rather than raising — an incomplete test fixture must not
    turn into a failed chat turn.
    """
    rows: list[tuple[str, TransactionListItem]] = []
    currencies: dict[str, int] = {}
    for txn in transactions:
        raw_id = getattr(txn, "id", None)
        currency = getattr(txn, "currency", None)
        date = getattr(txn, "transaction_date", None)
        if not isinstance(currency, str) or not isinstance(date, datetime.date):
            continue
        try:
            txn_id = uuid.UUID(str(raw_id))
            amount = float(getattr(txn, "amount", 0) or 0)
        except (TypeError, ValueError):
            continue
        rows.append(
            (
                currency,
                TransactionListItem(
                    id=txn_id,
                    title=getattr(txn, "merchant_normalized", None)
                    or getattr(txn, "merchant_raw", None)
                    or "Unknown",
                    category=(
                        txn.category.name if getattr(txn, "category", None) else "uncategorized"
                    ),
                    type=flow_for_type(getattr(txn, "transaction_type", None)),
                    amount=amount,
                    date=date,
                ),
            )
        )
        currencies[currency] = currencies.get(currency, 0) + 1

    if not rows:
        return None
    # One currency per payload, same rule the real display tools follow.
    chosen = sorted(currencies.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    kept = [item for currency, item in rows if currency == chosen]
    return TransactionsListWidget(
        payload=TransactionsListPayload(currency=chosen, transactions=kept)
    )


def _mock_breakdown_dates(text: str) -> tuple[str | None, str | None, str | None]:
    today = datetime.date.today()
    lowered = text.casefold()
    if "this month" in lowered or "current month" in lowered:
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat(), today.strftime("%B %Y")
    if "last month" in lowered or "previous month" in lowered:
        end = today.replace(day=1) - datetime.timedelta(days=1)
        start = end.replace(day=1)
        return start.isoformat(), end.isoformat(), end.strftime("%B %Y")
    return None, None, None


async def _mock_spending_breakdown(state: ConversationState, user_id) -> dict | None:
    last_msg = state["messages"][-1] if state.get("messages") else None
    text = getattr(last_msg, "content", "")
    if not isinstance(text, str):
        return None
    lowered = text.casefold()
    if not any(
        phrase in lowered for phrase in ("breakdown", "by category", "where did my money go")
    ):
        return None

    from app.tools.transactions import make_transaction_tools
    from app.tools.widgets import make_widget_tools

    date_from, date_to, month_label = _mock_breakdown_dates(text)
    transaction_tools = make_transaction_tools(user_id)
    widget_tools, sink = make_widget_tools(user_id, transaction_tools)
    breakdown_tool = next(tool for tool in widget_tools if tool.name == "show_spending_breakdown")
    result = await breakdown_tool.ainvoke(
        {
            "date_from": date_from,
            "date_to": date_to,
            "month_label": month_label,
            "currency": None,
        }
    )
    if not isinstance(result, dict) or not result.get("shown") or not sink:
        reason = result.get("reason") or result.get("error") if isinstance(result, dict) else None
        return {
            "messages": [
                AIMessage(content=reason or "I couldn't load that spending breakdown just now.")
            ],
            "message_references": [],
            "widget": None,
        }

    categories = result.get("categories") or []
    top = categories[0] if categories else None
    period = result.get("period") or "the selected period"
    reply = f"Your tracked spending for {period} is {result['total']:.2f} {result['currency']}."
    if top:
        reply += (
            f" Your largest category is {top['name']} at "
            f"{top['amount']:.2f} {result['currency']}."
        )
    return {
        "messages": [AIMessage(content=reply)],
        "message_references": [],
        "widget": sink[-1],
    }


async def _mock_analysis(state: ConversationState, user_id) -> dict:
    breakdown = await _mock_spending_breakdown(state, user_id)
    if breakdown is not None:
        return breakdown
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
        transaction_titles: list[str] = []
        widget: TransactionsListWidget | None = None
        async for session in get_backend_session():
            result = await session.execute(
                select(Transaction)
                .where(Transaction.user_id == user_id)
                .options(selectinload(Transaction.category))
                .limit(10)
            )
            transactions = result.scalars().all()
            widget = _mock_widget(transactions)

            for txn in transactions:
                references.append(Reference(target_type="transaction", target_id=str(txn.id)))
                title = (
                    getattr(txn, "merchant_normalized", None)
                    or getattr(txn, "merchant_raw", None)
                    or "Unknown"
                )
                transaction_titles.append(str(title)[:100])

        if not references:
            return {
                "messages": [
                    AIMessage(content="I don't have that data yet. No transactions found."),
                ],
                "message_references": [],
            }

        # Deliberately a one-line summary, not a per-row list, when a widget is
        # available: it already shows every row. Minimal fixtures and degraded
        # backend rows may not carry the currency/date fields required to build
        # that widget; in that case include the bounded merchant titles in the
        # prose so the response still contains the user's requested data.
        reply = f"Here are your {len(references)} most recent transactions."
        if widget is None and transaction_titles:
            reply += " " + "; ".join(transaction_titles)
        return {
            "messages": [AIMessage(content=reply)],
            "message_references": references,
            "widget": widget,
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
        from app.tools.widgets import make_widget_tools

        # Two tool families, one flat list for bind_tools: the transaction tools
        # answer the question, the widget tools additionally render it. The
        # widget sink is per-turn state the display tools append to — see
        # app/tools/widgets.py for why the payload is built there rather than
        # being asked of the model.
        transaction_tools = make_transaction_tools(user_id)
        widget_tools, widget_sink = make_widget_tools(user_id, transaction_tools)
        tools = [*transaction_tools, *widget_tools]
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
            content=ANALYSIS_SYSTEM_PROMPT_TEMPLATE.format(today=datetime.date.today().isoformat())
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
        # Last display tool called wins. Unlike planner/recommendation, this node
        # sets BOTH a widget and references: the references are the citation
        # trail for the prose answer and stay useful even when a widget renders.
        return {
            "messages": produced,
            "message_references": references,
            "widget": widget_sink[-1] if widget_sink else None,
        }
    except Exception as exc:
        # Reached almost exclusively on an LLM-call failure (timeout/provider
        # hiccup) — the tools themselves never raise up to here, they catch
        # their own DB failures and return {"error": ...} observations for
        # the model to react to (see the per-call try/except above). So the
        # message here must not claim a backend/DB outage it doesn't know
        # happened.
        logger.exception(
            "analysis_llm_call_failed",
            user_id=str(user_id),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {
            "messages": [
                AIMessage(
                    content="Sorry, I couldn't finish analyzing that just now — please try again."
                ),
            ],
            "message_references": [],
        }
