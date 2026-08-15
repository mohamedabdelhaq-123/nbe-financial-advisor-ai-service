"""Thin `POST /internal/chat` helper so scenarios don't hand-build the
request body and re-parse SSE inline."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

from redteam.runners.sse import get_done_payload, parse_sse_events


def send_chat_turn(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    message: str,
    user_id: uuid.UUID | str,
    conversation_id: str | None = None,
    initial_context: dict | None = None,
    refresh_context: bool = False,
) -> "ChatTurnResult":
    body: dict[str, Any] = {
        "conversation_id": conversation_id or str(uuid.uuid4()),
        "user_id": str(user_id),
        "message": message,
        "refresh_context": refresh_context,
    }
    if initial_context is not None:
        body["initial_context"] = initial_context

    response = client.post("/internal/chat", json=body, headers=auth_headers)
    return ChatTurnResult(response=response, conversation_id=body["conversation_id"])


class ChatTurnResult:
    def __init__(self, *, response: Any, conversation_id: str) -> None:
        self.response = response
        self.conversation_id = conversation_id

    @property
    def status_code(self) -> int:
        return self.response.status_code

    @property
    def events(self) -> list[dict[str, Any]]:
        return parse_sse_events(self.response.text)

    @property
    def done(self) -> dict[str, Any]:
        return get_done_payload(self.response.text)

    @property
    def reply_text(self) -> str:
        return self.done.get("content", "")
