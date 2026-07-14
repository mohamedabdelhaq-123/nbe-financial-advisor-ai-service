# Contract: POST /internal/transactions/embed

**Feature**: [../spec.md](../spec.md) | **Auth**: Bearer token (`require_token`, same as every other `/internal/*` route)

## Request

```json
{
  "transaction_ids": ["b3f1...-uuid", "9a02...-uuid"]
}
```

| Field | Type | Rule |
|---|---|---|
| `transaction_ids` | array of UUID strings | 1–500 items (FR-004, FR-013); duplicates are deduplicated server-side |

## Responses

### 200 OK — every transaction embedded (FR-006, FR-009, FR-010)

```json
{
  "results": [
    {"transaction_id": "b3f1...-uuid", "status": "embedded"},
    {"transaction_id": "9a02...-uuid", "status": "embedded"}
  ]
}
```

One entry per unique requested ID, always `"status": "embedded"` — a 200 response
only ever happens when the whole batch succeeded (all-or-nothing, FR-006/FR-010).

### 404 Not Found — one or more IDs don't exist (FR-006)

```json
{
  "detail": {
    "message": "One or more transaction IDs were not found",
    "invalid_transaction_ids": ["9a02...-uuid"]
  }
}
```

Raised as a plain `HTTPException(404, detail={"message": ..., "invalid_transaction_ids": [...]})`
— no custom exception handler (Constitution Principle VIII: reuse the plain
`HTTPException` pattern already used everywhere else in this service rather than
hand-rolling a flat-body handler). FastAPI wraps `detail` under a top-level
`"detail"` key automatically, so the body is one level nested, not flat. No
transaction in the request is written, including the ones that do exist
(all-or-nothing).

### 401 Unauthorized

Standard `ERROR_RESPONSES[401]` shape (missing/invalid Bearer token). No
transaction is read or written.

### 422 Unprocessable Entity — including empty or oversized batch (FR-004, FR-013)

Standard `ERROR_RESPONSES[422]` shape (malformed request body — not a UUID,
missing `transaction_ids`, etc.), produced automatically by the
`TransactionEmbedRequest` field validator. An empty `transaction_ids` list or a
list over 500 entries is rejected the same way — via that validator, not a
hand-written 400 branch — consistent with `/internal/embeddings`'s existing
blank-input validator, which surfaces the same way (see
`tests/features/embed/test_embed_router.py::test_embeddings_422_blank_input`):

```json
{"detail": [{"type": "value_error", "loc": ["body", "transaction_ids"], "msg": "Value error, transaction_ids must contain between 1 and 500 IDs", ...}]}
```

No transaction is read or written.

### 502 Bad Gateway — embedding provider unreachable/erroring (FR-010)

```json
{"detail": "Embedding provider unavailable"}
```

Matches the existing `/internal/embeddings` failure shape. No transaction is
written — the backend DB transaction is rolled back.

## Side effects on success

- Exactly one row in `ai_audit_log` is written (`action="transactions.embed"`,
  `detail_json={"transaction_ids": [...]}`), per FR-012.
- Exactly the `embedding` column of each named `transactions` row is updated; no
  other column is touched (FR-005).
