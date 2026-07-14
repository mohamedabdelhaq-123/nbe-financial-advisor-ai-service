# Quickstart: Chat Streaming Contract Alignment

**Feature**: [spec.md](./spec.md) | **Date**: 2026-07-14

Runnable validation for the new `/internal/chat` SSE contract. All scenarios
run mock-first (`USE_MOCK_LLM=1`) — no real model or network call is made
(Constitution Principle I). See [contracts/chat-stream.md](./contracts/chat-stream.md)
for the wire shapes and [data-model.md](./data-model.md) for the payload
definitions asserted below.

## Prerequisites

- Dependencies installed: `uv sync --frozen` exits 0.
- The service's auth token is available; tests inject it via the `auth_headers`
  fixture (see `tests/conftest.py`).
- No live LLM or backend is required — every scenario below runs in mock mode.

## Validation scenarios

### 1. Envelope — token + done, no `[DONE]` (US1 / FR-001, FR-002, FR-004)

`POST /internal/chat` with a valid token, mock mode on.

- Expect `200` and `content-type: text/event-stream`.
- The body contains at least one `{"event": "token", "data": "..."}` frame.
- The body contains exactly one `{"event": "done", "data": {...}}` frame.
- The body does NOT contain the legacy `data: [DONE]` line, nor any
  `{"type": "token", ...}` / `{"type": "error", ...}` frame.

Covered by `tests/features/chat/test_chat.py` (updated) and the envelope unit
tests in `tests/features/chat/test_schemas.py`.

### 2. Terminal payload shape (US1 / FR-003, FR-005, FR-008)

Inspect the `done` event emitted for a general reply.

- `data.content` is a non-empty string (the mock reply).
- `data.widget` is present and `null`.
- `data.references` is present and `[]`.
- `data` has NO `id` key (Django assigns it after persistence).

### 3. Widget emission (US2 / FR-005)

- A planning reply that reaches `plan_complete` → `done.data.widget == {"type":
  "allocation_slider", "payload": {"allocations": [...]}}`.
- A recommendation reply → `done.data.widget == {"type": "product_card",
  "payload": {"products": [...]}}`.
- A planner reply still asking a question → `done.data.widget is null`.

Exercised by extending the existing agent tests under
`tests/features/chat/` (each agent asserts the widget it returns).

### 4. Reference shape and vocabulary (US3 / FR-006, FR-007)

- An analysis reply grounded in transactions → `done.data.references` has one
  entry per cited transaction, each `{"target_type": "transaction",
  "target_id": "<uuid>"}`.
- A recommendation reply → `done.data.references == []` (products live in the
  widget, not references).
- Every `target_type` seen across all scenarios is `transaction` or
  `statement` only.

### 5. Incremental streaming on the real path (US1 / SC-002)

With a streaming-capable fake chat model standing in for `ChatOpenAI`
(injected via `monkeypatch` on `app.core.llm.get_chat_model`), drive
`stream_chat` and assert more than one `token` event is emitted before the
`done` event, and that every `token` chunk comes from a leaf agent node
(Maestro/summarizer tokens are NOT forwarded).

### 6. Error event uses the new envelope (FR-010)

Force a failure mid-stream (e.g. raise inside the graph). Expect exactly one
`{"event": "error", "data": {"message": "..."}}` frame, then the stream
closes with no `done` event.

### 7. Auth guard unchanged (FR-009)

`POST /internal/chat` without a Bearer token → `401`, nothing streamed.

## Run commands

```bash
# envelope + agents + schemas
uv run pytest tests/features/chat/ -q

# focused regression on the contract
uv run pytest tests/features/chat/test_chat.py tests/features/chat/test_schemas.py -q
```

## Expected outcome

All referenced tests pass; the suite makes no real model or network call; the
`/internal/chat` stream now emits the `{event, data}` envelope with a
structured terminal `done` event carrying `content`, `widget`, and
`references`, and no longer emits `data: [DONE]`.
