# Contract Amendment: Chat Request Shape (POST /internal/chat)

**Feature**: [../spec.md](../spec.md) | **Amends**: [`specs/009-chat-streaming-contract/contracts/chat-stream.md`](../../../009-chat-streaming-contract/contracts/chat-stream.md) | **Auth**: Bearer token (`require_token`) | **Breaking**: Yes.

## Summary

Two changes to the `ChatTurnRequest` request body, made as a post-implementation amendment within this feature (`research.md` D11), after the initial UUID-typing pass on `initial_context` (D3) turned out to be the wrong shape:

1. **`is_first_turn` is removed.** The service now unconditionally reads prior checkpointer state (`graph.aget_state`) on every turn instead of trusting a client-supplied flag to gate that read.
2. **`initial_context` carries no identity field.** It is a plain, optional `dict` of conversation context (e.g. account summary) — never `user_id`. `user_id` is, and has only ever needed to be, the request's root-level field.

## What changed

### Before (spec 009, and the 2026-07-14 pass of this feature)

```json
{
  "conversation_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
  "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
  "message": "How much did I spend on groceries last month?",
  "is_first_turn": true,
  "initial_context": {"user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"},
  "refresh_context": false
}
```

### After (this amendment)

```json
{
  "conversation_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
  "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
  "message": "How much did I spend on groceries last month?",
  "initial_context": {"monthly_income": 15000},
  "refresh_context": false
}
```

| Field | Before | After |
|---|---|---|
| `conversation_id` | `str` | unchanged |
| `user_id` | `UUID4` | unchanged — the single source of identity |
| `message` | `str` | unchanged |
| `is_first_turn` | `bool = False` | **removed** |
| `initial_context` | `UserContext \| None` (`{user_id: UUID4}`) | **`dict \| None`** — generic conversation context, no identity field |
| `refresh_context` | `bool = False` | unchanged (still not wired up in `chat/service.py` — pre-existing gap, out of scope) |

## Why

- **`user_id` inside `initial_context` was redundant** with the request-root `user_id` field, and risked the two copies drifting.
- **The `UserContext` name mislabeled the field.** `initial_context`'s own docstring always described it as "seed context (e.g. account summary)" — the sibling `/internal/plan/*` endpoint's own `user_context: dict` field (example: `{"monthly_income": 15000}`) confirms that's what "context" means elsewhere in this codebase. A `user_id`-only model with `extra="ignore"` would have silently dropped any such richer context Django sends, defeating the planner's LLM prompt (`plan/service.py generate_plan()`), which consumes `user_context` as an opaque blob of financial facts.
- **`is_first_turn` bought one cheap checkpointer read** and cost a correctness risk: a stale or wrong client flag could skip restoring real prior state. Reading it unconditionally removes that risk at negligible cost — verified live (below).

## What did NOT change

- The SSE response envelope, event types, and `done`/`error` payload shapes (untouched by this amendment — see the parent `chat-stream.md` contract and the `chat-stream-amendment.md` product_id amendment).
- The audit write (`ai_audit_log`, `action="chat_turn"`) — unchanged in shape; still fires once per turn.
- The `refresh_context` field's declared shape — still present, still not implemented in `chat/service.py` (a separate, pre-existing gap this amendment does not address).

## Migration for consumers

- **Django proxy**: stop sending `is_first_turn`; it is ignored if sent (Pydantic's default `extra="ignore"` on `ChatTurnRequest` tolerates it, so this is not a hard break for callers who haven't updated yet — but it does nothing). Stop nesting `user_id` inside `initial_context`; send only genuine conversation context there, if any.

## Verification

Validated live against a running dev instance: two turns sent on the same `conversation_id`, neither containing `is_first_turn`, correctly shared checkpointer message history and `user_id`, and each produced its own `ai_audit_log` row for the same UUID. See `quickstart.md` Step 2a.

## Cross-reference

- Parent feature: [../spec.md](../spec.md)
- Design decision: [../research.md](../research.md) D11 (supersedes D3)
- Data model: [../data-model.md](../data-model.md)
- Related amendment (product_id): [chat-stream-amendment.md](chat-stream-amendment.md)
- Full chat-stream contract: [`specs/009-chat-streaming-contract/contracts/chat-stream.md`](../../../009-chat-streaming-contract/contracts/chat-stream.md)
