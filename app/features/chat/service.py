"""Chat streaming service — SSE endpoint implementation."""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.core.logging import get_logger
from app.features.chat.routing import ROUTE_SPECS, ROUTES_BY_NAME
from app.features.chat.schemas import (
    AgentSelectedEvent,
    AgentSelectedPayload,
    ChatTurnRequest,
    DoneEvent,
    DonePayload,
    ErrorEvent,
    ErrorPayload,
    TokenEvent,
    ToolCallEvent,
    ToolCallPayload,
)

logger = get_logger(__name__)

# User-facing leaf agents whose token output is forwarded downstream.
# Maestro classification and summary generation are consumed internally.
# validate_answer is also internal: it emits a raw "Valid"/"Invalid: <reason>"
# classification string (plan/service.py's validate_answer_llm) that
# planner_ask later turns into the actual user-facing reprompt — it must
# never be streamed to the user directly.
_LEAF_NODES = frozenset(
    {
        "analysis",
        "planner_ask",
        "investment_plan",
        "recommendation",
        "general",
        "clarify",
        "refused",
    }
)

# Maps a leaf graph node back to its user-facing route name for the
# `agent_selected` event. Only the 5 real specialists have an entry —
# `clarify`/`refused` nodes delegate to no specialist, so looking either up
# here returns None, which is exactly how those two turns get excluded from
# `agent_selected` with no separate exclusion list to maintain.
_ROUTE_NAME_BY_GRAPH_NODE = {spec.graph_node: spec.name for spec in ROUTE_SPECS}


async def _conversation_belongs_to_user(conversation_id: str, user_id: uuid.UUID) -> bool:
    """Fail closed unless the backend mirror confirms the conversation owner.

    The internal bearer token authenticates the Django service, not the end
    user represented by request fields. Checking the owner here prevents a
    caller that supplies another user's conversation ID from loading that
    thread's LangGraph checkpoint, messages, questionnaire answers, or cached
    financial context.
    """
    try:
        parsed_conversation_id = uuid.UUID(conversation_id)
    except (TypeError, ValueError):
        logger.warning("conversation_ownership_invalid_id")
        return False

    try:
        from sqlalchemy import select

        from app.backend_db import get_backend_session
        from app.backend_db.models import Conversation

        async for session in get_backend_session():
            result = await session.execute(
                select(Conversation.user_id).where(Conversation.id == parsed_conversation_id)
            )
            owner_id = result.scalar_one_or_none()
            return owner_id == user_id
    except Exception:
        logger.exception(
            "conversation_ownership_check_failed",
            conversation_id=str(parsed_conversation_id),
        )
        return False

    return False


# Tool names bound in analysis.py's _agentic_analysis — the only node that
# calls bind_tools(). Against OpenAI itself a tool call always rides in the
# message's structured tool_calls field with empty `content`, so intermediate
# turns never leak into the token stream. Some OpenAI-compatible self-hosted
# backends (vLLM etc. — see app/core/llm.py) emulate tool-calling by having
# the model literally emit the call as XML-ish text in `content` (e.g.
# `<show_transactions count="10"></show_transactions>`), which their own
# tool-call parser then strips out of the FINAL assembled response but not
# necessarily out of each streamed delta — so the raw tag text can reach the
# client as one or more `token` events before it's recognized as a tool call.
# This is a defensive strip, not the root cause fix (that would require
# buffering per-turn to detect a tool call before forwarding anything, which
# would give up incremental streaming for the analysis node entirely) — it
# just keeps the known tag shapes out of what the user ever sees, on both the
# streamed chunks and the final persisted content.
_TOOL_NAMES = (
    "show_spending_breakdown",
    "show_transactions",
    "show_savings_projection",
    "get_transactions",
    "compute_aggregate",
    "find_similar_transactions",
)
_TOOL_TAG_RE = re.compile(
    r"<(?:" + "|".join(_TOOL_NAMES) + r")\b[^>]*?(?:/>|>.*?</(?:" + "|".join(_TOOL_NAMES) + r")>)",
    re.DOTALL,
)


def _strip_tool_call_tags(text: str) -> str:
    """Removes any recognized `<tool_name ...>...</tool_name>` (or
    self-closing `<tool_name .../>`) block from model output text — see
    `_TOOL_TAG_RE`'s comment above for why these sometimes leak through."""
    if "<" not in text:
        return text
    return _TOOL_TAG_RE.sub("", text)


def _tool_call_frame(call_id: str, tool: str, status: Literal["started", "completed"]) -> str:
    """One `tool_call` SSE frame — see `ToolCallEvent`'s docstring for what this
    signals (best-effort, analysis node only) and why a client shouldn't
    depend on it for correctness."""
    payload = ToolCallEvent(data=ToolCallPayload(call_id=call_id, tool=tool, status=status))
    return f"data: {payload.model_dump_json()}\n\n"


def _agent_selected_frame(agent: str) -> str:
    """One `agent_selected` SSE frame — see `AgentSelectedEvent`'s docstring
    for the two emission points (first leaf-node chunk, or the interrupt
    fallback) that both funnel through this helper."""
    payload = AgentSelectedEvent(data=AgentSelectedPayload(agent=agent))
    return f"data: {payload.model_dump_json()}\n\n"


async def stream_chat(app, request: ChatTurnRequest) -> AsyncIterator[str]:
    """Yield the SSE frames for one chat turn over the shared ``{event, data}`` envelope.

    Emits at most one ``agent_selected`` event naming the route Maestro chose
    (absent for ``clarify``/``refused`` turns, which delegate to no
    specialist), followed by zero or more ``token`` events — one per
    non-empty content chunk from a leaf agent in ``_LEAF_NODES`` (Maestro
    classification, summary generation, and answer validation are consumed
    internally and never forwarded), optionally interleaved with best-effort
    ``tool_call`` events during the ``analysis`` node's tool-calling loop —
    then exactly one terminal event:

    * ``done`` — assembled from ``graph.aget_state`` after the stream drains,
      carrying the finalized ``content``, the ``widget`` slot (nullable), the
      ``references`` list (possibly empty), and up to 4 ``suggestions`` (best-effort;
      falls back to a static list rather than failing the turn — see
      app.features.chat.suggestions). Per FR-003 the payload carries **no**
      message ``id`` — Django assigns that after persistence.
    * ``error`` — exactly one on a production failure (FR-010); no ``done`` follows.

    ``asyncio.CancelledError`` (client disconnect) returns immediately with no
    partial ``done`` and no audit double-write, leaving checkpointer state
    consistent for the next turn. Generic mock-mode turns adopt the same
    envelope as a single ``token`` batch plus one ``done`` (FR-011), while the
    deterministic investment questionnaire still traverses the graph so its
    offline Docker flow is fully testable.
    """
    from app.core.config import settings

    if not await _conversation_belongs_to_user(
        request.conversation_id,
        request.user_id,
    ):
        logger.warning(
            "conversation_access_denied",
            conversation_id=request.conversation_id,
            user_id=str(request.user_id),
        )
        error = ErrorEvent(
            data=ErrorPayload(message="Conversation not available.")
        ).model_dump_json()
        yield f"data: {error}\n\n"
        return

    checkpointer = getattr(app.state, "checkpointer", None)
    graph = None
    config = {"configurable": {"thread_id": request.conversation_id}}
    snapshot = None

    if settings.chat_model.use_mock and checkpointer is None:
        # Transport-only tests may construct the app without running its
        # lifespan/checkpointer. A real service instance always uses the graph,
        # even in mock mode, so no user-facing turn is bypassed by keyword logic.
        from app.features.chat.suggestions import generate_suggestions

        mock_content = f"Mock response to: {request.message[:50]}"
        yield f"data: {TokenEvent(data=mock_content).model_dump_json()}\n\n"
        mock_suggestions = await generate_suggestions(mock_content, widget=None)
        mock_done = DonePayload(content=mock_content, suggestions=mock_suggestions)
        yield f"data: {DoneEvent(data=mock_done).model_dump_json()}\n\n"
        return

    if checkpointer is None:
        err = ErrorEvent(data=ErrorPayload(message="Chat not available.")).model_dump_json()
        yield f"data: {err}\n\n"
        return

    if graph is None:
        from app.features.chat.graph import build_graph

        graph = build_graph(checkpointer=checkpointer)
    if snapshot is None:
        snapshot = await graph.aget_state(config)
    prev_values = snapshot.values if snapshot else {}

    if snapshot and snapshot.interrupts:
        # The planner's ask/validate loop paused on interrupt() waiting for
        # this exact answer — Command(resume=...) resumes that same paused
        # node directly. It carries only the resume value, not a fresh
        # messages list (planner_ask_node appends the HumanMessage itself
        # once resumed) — building the state dict below is skipped entirely
        # on this path since the graph doesn't take a fresh state argument
        # when resuming.
        run_input: dict | Command = Command(resume=request.message)
    else:
        initial_messages = [HumanMessage(content=request.message)]
        conversation_context = (
            request.initial_context
            if request.initial_context is not None
            else prev_values.get("user_context")
        )
        run_input = {
            "messages": initial_messages,
            "user_id": request.user_id,
            "user_context": conversation_context,
            # Restore the persisted stage so Maestro can detect mid-planning turns.
            "stage": prev_values.get("stage", ""),
            # Preserve the previous route for optional NLI-shadow context.
            # Maestro overwrites it with the current structured decision.
            "intent": prev_values.get("intent", ""),
            # The last capability that actually routed — survives clarify/
            # refuse turns by construction (see state.py) since only this
            # explicit carry-forward and maestro_node's own writes ever touch
            # it. Not required for the value to persist (LangGraph's partial
            # merge already preserves an omitted key against the checkpoint),
            # but made explicit here to match every other carried field.
            "last_active_route": prev_values.get("last_active_route"),
            "routing_outcome": "route",
            "routing_confidence": 0.0,
            "routing_clarification": None,
            "planner_answers": dict(prev_values.get("planner_answers") or {}),
            "questions_asked": prev_values.get("questions_asked", 0),
            "last_question_id": prev_values.get("last_question_id"),
            "planner_validation_attempts": prev_values.get("planner_validation_attempts", 0),
            "planner_context": prev_values.get("planner_context"),
            "investment_answers": dict(prev_values.get("investment_answers") or {}),
            "investment_context": prev_values.get("investment_context"),
            "investment_validation_attempts": prev_values.get("investment_validation_attempts", 0),
            "investment_validation_reason": prev_values.get("investment_validation_reason"),
            "pending_answer": prev_values.get("pending_answer"),
            "pending_validation_reason": prev_values.get("pending_validation_reason"),
            "message_references": [],
            "widget": None,
        }

    try:
        # FR-001/FR-004: stream incremental token events for leaf-agent output only.
        announced_call_ids: set[str] = set()
        announced_agent = False
        async for chunk, metadata in graph.astream(run_input, config, stream_mode="messages"):
            if metadata.get("langgraph_node") in _LEAF_NODES:
                if not announced_agent:
                    announced_agent = True
                    try:
                        agent_name = _ROUTE_NAME_BY_GRAPH_NODE.get(metadata.get("langgraph_node"))
                        if agent_name:
                            yield _agent_selected_frame(agent_name)
                    except Exception:
                        logger.warning("agent_selected_event_emit_failed", exc_info=True)
                # stream_mode="messages" replays *every* message a node emits,
                # not just the model's prose — the analysis agent's tool-calling
                # loop also appends ToolMessages (raw JSON tool results), and
                # planner_ask_node re-appends the user's own HumanMessage to
                # history when a resumed interrupt() turn completes. AIMessage
                # content is the model's actual reply; ToolMessage content (raw
                # JSON) is never streamed as a token. Both message types do
                # carry tool-call lifecycle info, surfaced below as best-effort
                # `tool_call` events — each wrapped in its own try/except so a
                # bug in this newer, less-tested path degrades to "no
                # indicator for this step" rather than aborting an otherwise-
                # working reply via the outer except below.
                if isinstance(chunk, ToolMessage):
                    try:
                        if chunk.name:
                            yield _tool_call_frame(chunk.tool_call_id, chunk.name, "completed")
                    except Exception:
                        logger.warning("tool_call_event_emit_failed", exc_info=True)
                    continue
                if not isinstance(chunk, AIMessage):
                    continue
                try:
                    for call in getattr(chunk, "tool_calls", None) or []:
                        call_id = call.get("id")
                        if call_id and call_id not in announced_call_ids:
                            announced_call_ids.add(call_id)
                            yield _tool_call_frame(call_id, call["name"], "started")
                except Exception:
                    logger.warning("tool_call_event_emit_failed", exc_info=True)
                content = chunk.content
                if isinstance(content, str) and content:
                    content = _strip_tool_call_tags(content)
                    if content:
                        yield f"data: {TokenEvent(data=content).model_dump_json()}\n\n"

        # FR-002/FR-005/FR-008: exactly one terminal done assembled from finalized state.
        snapshot = await graph.aget_state(config)
        values = snapshot.values if snapshot else {}

        if snapshot and snapshot.interrupts:
            # The planner just paused asking a question — its text lives on
            # the interrupt payload, not in `messages`. planner_ask_node
            # only appends to `messages` in the return statement right
            # after interrupt() resumes, which doesn't happen until the
            # NEXT turn — reading `messages[-1]` here would echo the user's
            # own input back to them instead of the actual question, since
            # nothing has been appended to message history yet this turn.
            #
            # A fresh (non-resumed) planner_ask/investment_plan turn calls
            # interrupt() before any `return`, which LangGraph intercepts as
            # a control-flow exception — no chunk is ever emitted for that
            # invocation, so the primary path above never fires. `intent` is
            # the same state key graph.py's _route_intent() reads to route
            # in the first place, and already holds a route *name* (not a
            # graph node), so it's a reliable substitute here.
            if not announced_agent:
                try:
                    agent_name = values.get("intent")
                    if agent_name and agent_name in ROUTES_BY_NAME:
                        yield _agent_selected_frame(agent_name)
                except Exception:
                    logger.warning("agent_selected_event_emit_failed", exc_info=True)
            content = snapshot.interrupts[0].value.get("text", "")
            if content:
                yield f"data: {TokenEvent(data=content).model_dump_json()}\n\n"
        else:
            messages = values.get("messages") or []
            content = ""
            if messages:
                last_msg = messages[-1]
                last_content = getattr(last_msg, "content", "")
                if isinstance(last_content, str):
                    content = last_content
                elif last_content:
                    content = str(last_content)

        from app.features.chat.suggestions import generate_suggestions

        content = _strip_tool_call_tags(content)
        widget = values.get("widget")
        suggestions = await generate_suggestions(content, widget)
        done_payload = DonePayload(
            content=content,
            widget=widget,
            references=list(values.get("message_references") or []),
            suggestions=suggestions,
        )
        yield f"data: {DoneEvent(data=done_payload).model_dump_json()}\n\n"
    except asyncio.CancelledError:
        # Client disconnect (T010a): stop producing immediately — no partial done,
        # no error event, no audit write. Checkpointer state stays consistent.
        return
    except Exception:
        # FR-010: exactly one error event, then the stream closes (no done follows).
        # Log the real exception server-side only — the client gets a generic
        # message so internal details (paths, connection strings, etc.) never leak.
        logger.exception("chat_turn_stream_failed", conversation_id=request.conversation_id)
        generic_error = ErrorEvent(
            data=ErrorPayload(message="Something went wrong. Please try again.")
        )
        yield f"data: {generic_error.model_dump_json()}\n\n"

    # FR-013: unchanged best-effort audit write after the stream ends.
    try:
        from app.core.audit import record_audit
        from app.core.db import OwnSession

        async with OwnSession() as session:
            await record_audit(
                session,
                user_id=request.user_id,
                action="chat_turn",
                detail={
                    "conversation_id": request.conversation_id,
                    "message": request.message[:200],
                },
            )
            # record_audit() only flushes; this call site needs the row to be
            # durably persisted, so commit explicitly rather than relying on
            # the caller's session scope to do it (matches the pattern used
            # at the other record_audit() call sites).
            await session.commit()
    except Exception:
        pass
