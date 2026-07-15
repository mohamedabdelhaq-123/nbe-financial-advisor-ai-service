# Contract: POST /internal/chat (SSE stream)

**Feature**: [../spec.md](../spec.md) | **Auth**: Bearer token (`require_token`,
same as every other `/internal/*` route) | **Proxy**: Django proxies this
stream verbatim to the frontend over `POST /chat/conversations/{id}/messages`
(see backend `Data_Shapes_Conversations.md`).

## Request

```json
{
  "conversation_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
  "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
  "message": "How much did I spend on groceries last month?",
  "initial_context": null,
  "refresh_context": false
}
```

Not modified by spec 009 itself, but amended twice by spec `010-fix-uuid-id-types`:
`user_id` became a validated `UUID4` (was `int`), and — as a post-implementation
amendment within that same feature — `is_first_turn` was removed and
`initial_context` was confirmed as generic, identity-unrelated conversation
context rather than a place to duplicate `user_id`. See
[`specs/010-fix-uuid-id-types/contracts/chat-request-amendment.md`](../../010-fix-uuid-id-types/contracts/chat-request-amendment.md)
for the full amendment.

## Response `200` — `text/event-stream`

A sequence of Server-Sent Events, one per line, each framed as
`data: <json>\n\n`. Every event shares one envelope:
`{"event": <type>, "data": <payload>}` (FR-004).

### Event: `token` — incremental reply fragment (FR-001)

```json
{"event": "token", "data": "How much "}
```

`data` is a raw string — a small fragment of the assistant's reply, streamed
as it is generated. On the **real** path, many `token` events precede the
terminal event; on the **mock** path (`USE_MOCK_LLM=1`) exactly one `token`
event carries the whole mock reply (FR-011 — same envelope, single batch).

Only the selected leaf agent's tokens are forwarded; Maestro classification
and summary generation are never streamed (see
[../research.md](../research.md)).

### Event: `done` — terminal, finalized reply (FR-002, FR-005, FR-008)

Exactly one per turn, emitted after the stream drains:

```json
{
  "event": "done",
  "data": {
    "content": "You spent 1,240 EGP on groceries last month across 9 transactions.",
    "widget": null,
    "references": [
      {"target_type": "transaction", "target_id": "b3f1c2d4-..."},
      {"target_type": "transaction", "target_id": "9a02...-uuid"}
    ]
  }
}
```

| Field | Type | Rule |
|---|---|---|
| `content` | `str` | The complete finalized reply text; MAY be empty but the field is always present |
| `widget` | `object \| null` | Always present. `null` for `general`/`analysis` and while the planner asks questions; `{"type": "allocation_slider", "payload": {...}}` for a completed plan; `{"type": "product_card", "payload": {...}}` for recommendations (see [../data-model.md](../data-model.md)) |
| `references` | `list` | Always present, possibly `[]`. Each entry is `{"target_type": "transaction"\|"statement", "target_id": "<uuid>"}` (FR-006, FR-007) |

**The `done` event MUST NOT contain an `id` field** (FR-003). Django assigns
the persisted assistant message identifier after the stream completes.

### Event: `error` — production failure (FR-010)

Exactly one, then the stream closes (no `done` follows an `error`):

```json
{"event": "error", "data": {"message": "<reason>"}}
```

Replaces the prior `{"type": "error", "content": "..."}` shape.

### Removed (breaking vs. current output)

- The old `{"type": "token", "content": "..."}` frame is gone (use
  `{"event": "token", "data": "..."}`).
- The bare terminal `data: [DONE]` line is gone (replaced by the structured
  `done` event above).

## Response shapes outside the stream

### 401 Unauthorized

Standard `ERROR_RESPONSES[401]` shape (missing/invalid Bearer token). Nothing
is streamed — `require_token` rejects before the stream starts.

## Side effects on success

- The own-DB checkpointer persists the turn's `ConversationState` (now
  including the `widget` value) under `thread_id = conversation_id`, as today.
- Exactly one `ai_audit_log` row is written (`action="chat_turn"`,
  `detail_json={"conversation_id": ..., "message": <truncated>}`), as today —
  this feature changes neither the action nor the detail captured.
- No backend DB write occurs (FR-013).

## Continuity guarantee (FR-012)

Multi-turn state resumption (per-thread state read on non-first turns,
mid-questionnaire answer capture) is unchanged by the new streaming format —
the driver reads the same `aget_state` snapshot it reads today; only the
*emission* of the reply changes.
