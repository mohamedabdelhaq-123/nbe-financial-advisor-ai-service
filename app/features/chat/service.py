"""Chat streaming service — SSE endpoint implementation."""

import asyncio
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

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
# validate_answer is also internal: it emits a raw "Valid"/"Invalid: <reason>"
# classification string (plan/service.py's validate_answer_llm) that
# planner_ask later turns into the actual user-facing reprompt — it must
# never be streamed to the user directly.
_LEAF_NODES = frozenset(
    {"analysis", "planner_ask", "investment_plan", "recommendation", "general"}
)


async def stream_chat(app, request: ChatTurnRequest) -> AsyncIterator[str]:
    """Yield the SSE frames for one chat turn over the shared ``{event, data}`` envelope.

    Emits zero or more ``token`` events — one per non-empty content chunk from a
    leaf agent in ``_LEAF_NODES`` (Maestro classification, summary generation,
    and answer validation are consumed internally and never forwarded) — then
    exactly one terminal event:

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

    checkpointer = getattr(app.state, "checkpointer", None)
    graph = None
    config = {"configurable": {"thread_id": request.conversation_id}}
    snapshot = None

    # Investment planning is deliberately deterministic except for its quote
    # provider, so it remains fully exercisable when the chat LLM is mocked.
    # Existing generic mock-chat behaviour stays intact for all other fresh
    # turns. A pending interrupt also has to resume through the graph because
    # terse questionnaire answers do not carry an investment keyword.
    if settings.chat_model.use_mock and checkpointer is not None:
        from app.features.chat.agents.maestro import classify_intent
        from app.features.chat.graph import build_graph

        graph = build_graph(checkpointer=checkpointer)
        snapshot = await graph.aget_state(config)
        classified_intent = classify_intent(request.message)
        is_task_turn = classified_intent != "general"
        is_completed_plan_edit = False
        if snapshot and snapshot.values.get("stage") == "investment_plan_complete":
            from app.features.chat.agents.investment import parse_instrument_selection

            is_completed_plan_edit = bool(
                parse_instrument_selection(
                    request.message,
                    snapshot.values.get("investment_context"),
                    snapshot.values.get("investment_answers"),
                )
            )
        has_pending_question = bool(snapshot and snapshot.interrupts)
    else:
        is_task_turn = False
        is_completed_plan_edit = False
        has_pending_question = False

    if settings.chat_model.use_mock and not (
        is_task_turn or is_completed_plan_edit or has_pending_question
    ):
        # FR-011: mock mode adopts the same envelope (one token batch + one done).
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
            "intent": "",
            "planner_answers": dict(prev_values.get("planner_answers") or {}),
            "questions_asked": prev_values.get("questions_asked", 0),
            "last_question_id": prev_values.get("last_question_id"),
            "planner_validation_attempts": prev_values.get("planner_validation_attempts", 0),
            "planner_context": prev_values.get("planner_context"),
            "investment_answers": dict(prev_values.get("investment_answers") or {}),
            "investment_context": prev_values.get("investment_context"),
            "investment_validation_attempts": prev_values.get(
                "investment_validation_attempts", 0
            ),
            "investment_validation_reason": prev_values.get("investment_validation_reason"),
            "pending_answer": prev_values.get("pending_answer"),
            "pending_validation_reason": prev_values.get("pending_validation_reason"),
            "message_references": [],
            "widget": None,
        }

    try:
        # FR-001/FR-004: stream incremental token events for leaf-agent output only.
        async for chunk, metadata in graph.astream(run_input, config, stream_mode="messages"):
            if metadata.get("langgraph_node") in _LEAF_NODES:
                # stream_mode="messages" replays *every* message a node emits,
                # not just the model's prose — the analysis agent's tool-calling
                # loop also appends ToolMessages (raw JSON tool results), and
                # planner_ask_node re-appends the user's own HumanMessage to
                # history when a resumed interrupt() turn completes. Only
                # AIMessage content is the model's actual reply, so anything
                # else is skipped rather than streamed to the client.
                if not isinstance(chunk, AIMessage):
                    continue
                content = chunk.content
                if isinstance(content, str) and content:
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
