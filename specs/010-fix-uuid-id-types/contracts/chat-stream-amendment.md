# Contract Amendment: Chat Stream Widget `product_id` (POST /internal/chat)

**Feature**: [../spec.md](../spec.md) | **Amends**: [`specs/009-chat-streaming-contract/contracts/chat-stream.md`](../../../009-chat-streaming-contract/contracts/chat-stream.md) | **Auth**: Bearer token (`require_token`) | **Breaking**: Yes (type change only — value shape unchanged).

## Summary

The `product_id` field inside the `product_card` widget payload of the terminal `done` event changes type from `str` to `UUID4`. The value shape (a canonical hyphenated UUID string on the wire) is unchanged — every UUID is already serialized as a hyphenated string over JSON. What changes is the **declared** type in the OpenAPI schema and the **validation** applied to outgoing values: non-UUID strings (e.g. the prior fabricated `"sav-001"`, `"cc-002"`) can no longer be carried.

This amendment is forced by the parent feature's end-to-end UUID consistency fix: the recommendation feature's `ProductMatch.product_id` is now `UUID4`, and the chat widget payload's `product_id` must agree.

## What changed

### Before (spec 009)

```json
{
  "event": "done",
  "data": {
    "content": "Here are some products that might suit you: ...",
    "widget": {
      "type": "product_card",
      "payload": {
        "products": [
          {
            "product_id": "sav-001",
            "product_name": "High-Yield Savings",
            "similarity": 0.92
          }
        ]
      }
    },
    "references": []
  }
}
```

`product_id` schema: `{ "type": "string" }`.

### After (this feature)

```json
{
  "event": "done",
  "data": {
    "content": "Here are some products that might suit you: ...",
    "widget": {
      "type": "product_card",
      "payload": {
        "products": [
          {
            "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
            "product_name": "High-Yield Savings",
            "similarity": 0.92
          }
        ]
      }
    },
    "references": []
  }
}
```

`product_id` schema: `{ "type": "string", "format": "uuid" }` (Pydantic `UUID4`).

## What did NOT change

- The shared `{"event", "data"}` envelope.
- The `token` / `done` / `error` event structure.
- The other two payload fields: `product_name` (now sourced from the backend `Products.title` — see parent feature `research.md` D4 — but the field shape is unchanged) and `similarity` (`float`, 0.0–1.0).
- The other widget type (`allocation_slider`) — unaffected.
- The `references` list shape (`{target_type, target_id}`).
- The "no `id` on `done`" rule (FR-003 of spec 009) — Django still assigns the persisted message ID after the stream.
- Auth, error semantics, side effects, multi-turn continuity (FR-012), audit-row write (FR-013).

## Migration for consumers

- **Django proxy**: parse `product_id` as a UUID string. Already-tolerant string parsers need no change; parsers that validated against a known enum (`sav-001`, `cc-002`) must be relaxed to accept any UUID.
- **Frontend**: treat `product_id` as an opaque UUID string for display and deeplinking. No format-specific behavior should have depended on the old `"sav-001"` shape.

## Test impact

- `tests/features/chat/test_schemas.py` — examples `"1"` → realistic UUID4 string.
- `tests/features/chat/test_recommendation_integration.py` — `ProductMatch(product_id=1, ...)` → `UUID4` value; line 47's assertion `widget.payload.products[0].product_id == "1"` becomes a UUID equality check (no str cast at the boundary anymore).

## Cross-reference

- Parent feature: [../spec.md](../spec.md)
- Standalone recommendations contract (also established by this feature): [recommendations-match.md](recommendations-match.md)
- Related amendment (request shape — `is_first_turn` removal, `initial_context` reshape): [chat-request-amendment.md](chat-request-amendment.md)
- Full chat-stream contract: [`specs/009-chat-streaming-contract/contracts/chat-stream.md`](../../../009-chat-streaming-contract/contracts/chat-stream.md)
