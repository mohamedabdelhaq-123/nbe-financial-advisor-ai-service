# Quickstart: Transaction Embedding by ID

**Feature**: [spec.md](./spec.md) | **Contract**: [contracts/transactions-embed.md](./contracts/transactions-embed.md)

## Prerequisites

- Service running locally in mock mode (`USE_MOCK_LLM=1`, the test/dev default —
  see `tests/conftest.py`), so no real embedding-provider network call is made.
- A backend Postgres reachable with the `ai_readonly` role (Testcontainers-provided
  in automated tests; a real backend DB with the grants from
  `core/migrations/0009_grant_ai_readonly_role.py` applied for manual/local runs).
- At least one row in `transactions` to target.

## Automated validation (primary path)

The integration tests are the source of truth for "this feature works end to end."
Run the full suite, or just this feature's slice once tests exist:

```bash
uv run pytest tests/features/transactions/ -v
```

Expected coverage (per FR/SC mapping):
- A batch of valid, never-embedded transaction IDs → 200, every ID reported
  `"embedded"`, and each row's `embedding` in the DB is a non-null vector of length
  `TRANSACTION_EMBEDDING_DIM` (US1, SC-001, SC-002).
- Re-embedding an already-embedded transaction → 200, the stored vector changes
  from its prior value (US2, FR-007).
- A batch mixing valid and nonexistent IDs → 404, `invalid_transaction_ids` names
  exactly the bad ones, and none of the valid IDs' rows are touched — verified by
  reading them back unchanged (US3, SC-003).
- No non-`embedding` column changes on any touched row, before vs. after (SC-004).
- Missing/invalid Bearer token → 401, nothing written.
- Empty `transaction_ids` → 422, nothing written.
- More than 500 `transaction_ids` → 422, nothing written; exactly 500 is accepted.
- Simulated embedding-provider failure mid-batch → 502, no row's `embedding`
  changes (FR-010).
- One `ai_audit_log` row per successful request, `action="transactions.embed"`
  (FR-012).

## Manual smoke test

```bash
curl -sS -X POST http://localhost:8000/internal/transactions/embed \
  -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"transaction_ids": ["<existing-transaction-uuid>"]}' | jq
```

Expected: `{"results": [{"transaction_id": "<uuid>", "status": "embedded"}]}`. A
`SELECT embedding FROM transactions WHERE id = '<uuid>'` immediately after should
show a non-null vector.
