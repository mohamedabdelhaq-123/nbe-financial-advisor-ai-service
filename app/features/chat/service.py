"""Chat streaming service — SSE endpoint implementation."""

import asyncio
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage

from app.core.logging import get_logger
from app.features.chat.schemas import (
    ChatTurnRequest,
    DoneEvent,
    DonePayload,
    ErrorEvent,
    ErrorPayload,
    TokenEvent,
)

logger = get_logger(__name__)

# User-facing leaf agents whose token output is forwarded downstream.
# Maestro classification and summary generation are consumed internally.
_LEAF_NODES = frozenset({"analysis", "planner", "recommendation", "general"})


async def stream_chat(app, request: ChatTurnRequest) -> AsyncIterator[str]:
    """Yield the SSE frames for one chat turn over the shared ``{event, data}`` envelope.

    Emits zero or more ``token`` events — one per non-empty content chunk from a
    leaf agent in ``_LEAF_NODES`` (Maestro classification and summary generation
    are consumed internally and never forwarded) — then exactly one terminal event:

    * ``done`` — assembled from ``graph.aget_state`` after the stream drains,
      carrying the finalized ``content``, the ``widget`` slot (nullable), and the
      ``references`` list (possibly empty). Per FR-003 the payload carries **no**
      message ``id`` — Django assigns that after persistence.
    * ``error`` — exactly one on a production failure (FR-010); no ``done`` follows.

    ``asyncio.CancelledError`` (client disconnect) returns immediately with no
    partial ``done`` and no audit double-write, leaving checkpointer state
    consistent for the next turn. Mock mode (``USE_MOCK_LLM``) adopts the same
    envelope as a single ``token`` batch plus one ``done`` (FR-011), so
    backend/frontend development does not branch on the mode.
    """
    from app.core.config import settings

    checkpointer = getattr(app.state, "checkpointer", None)

    if settings.chat_model.use_mock:
        # FR-011: mock mode adopts the same envelope (one token batch + one done).
        mock_content = f"Mock response to: {request.message[:50]}"
        yield f"data: {TokenEvent(data=mock_content).model_dump_json()}\n\n"
        yield f"data: {DoneEvent(data=DonePayload(content=mock_content)).model_dump_json()}\n\n"
        return

    if checkpointer is None:
        err = ErrorEvent(data=ErrorPayload(message="Chat not available.")).model_dump_json()
        yield f"data: {err}\n\n"
        return

    from app.features.chat.graph import build_graph

    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": request.conversation_id}}

    snapshot = await graph.aget_state(config)
    prev_values = snapshot.values if snapshot else {}

    initial_messages = [HumanMessage(content=request.message)]
    conversation_context = (
        request.initial_context
        if request.initial_context is not None
        else prev_values.get("user_context")
    )
    planner_answers = dict(prev_values.get("planner_answers") or {})
    questions_asked = prev_values.get("questions_asked", 0)
    # Restore the persisted stage so Maestro can detect mid-planning turns.
    stage = prev_values.get("stage", "")

    if questions_asked > 0 and stage != "plan_complete":
        from app.features.plan.service import QUESTIONS

        idx = questions_asked - 1
        if idx < len(QUESTIONS):
            answered_id = QUESTIONS[idx].id
            planner_answers.setdefault(answered_id, request.message)

    state = {
        "messages": initial_messages,
        "user_id": request.user_id,
        "user_context": conversation_context,
        "stage": stage,
        "intent": "",
        "planner_answers": planner_answers,
        "questions_asked": questions_asked,
        "message_references": [],
        "widget": None,
    }

    try:
        # FR-001/FR-004: stream incremental token events for leaf-agent output only.
        async for chunk, metadata in graph.astream(state, config, stream_mode="messages"):
            if metadata.get("langgraph_node") in _LEAF_NODES:
                content = chunk.content
                if isinstance(content, str) and content:
                    yield f"data: {TokenEvent(data=content).model_dump_json()}\n\n"

        # FR-002/FR-005/FR-008: exactly one terminal done assembled from finalized state.
        snapshot = await graph.aget_state(config)
        values = snapshot.values if snapshot else {}
        messages = values.get("messages") or []
        content = ""
        if messages:
            last_msg = messages[-1]
            last_content = getattr(last_msg, "content", "")
            if isinstance(last_content, str):
                content = last_content
            elif last_content:
                content = str(last_content)
        done_payload = DonePayload(
            content=content,
            widget=values.get("widget"),
            references=list(values.get("message_references") or []),
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
