"""Chat streaming service — SSE endpoint implementation."""

import json
from collections.abc import AsyncIterator

from app.features.chat.schemas import ChatTurnRequest


async def stream_chat(app, request: ChatTurnRequest) -> AsyncIterator[str]:
    from app.core.config import settings

    checkpointer = getattr(app.state, "checkpointer", None)

    if settings.use_mock_llm:
        mock_content = f"Mock response to: {request.message[:50]}"
        yield f"data: {json.dumps({'type': 'token', 'content': mock_content})}\n\n"
        yield "data: [DONE]\n\n"
        return

    if checkpointer is None:
        err_payload = json.dumps({"type": "error", "content": "Chat not available."})
        yield f"data: {err_payload}\n\n"
        yield "data: [DONE]\n\n"
        return

    from app.features.chat.graph import build_graph

    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": request.conversation_id}}

    initial_messages = [request.message]
    user_context = {}
    if request.is_first_turn and request.initial_context:
        user_context = request.initial_context

    state = {
        "messages": initial_messages,
        "user_context": user_context,
        "stage": "",
        "intent": "",
        "planner_answers": {},
        "questions_asked": 0,
        "message_references": [],
    }

    try:
        result = await graph.ainvoke(state, config)
        messages = result.get("messages", [])
        for msg in messages:
            if hasattr(msg, "content") and msg.content:
                yield f"data: {json.dumps({'type': 'token', 'content': msg.content})}\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    yield "data: [DONE]\n\n"

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
    except Exception:
        pass
