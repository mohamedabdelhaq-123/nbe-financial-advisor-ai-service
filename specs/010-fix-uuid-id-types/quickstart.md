# Quickstart: UUID Identifier Consistency

**Feature**: [spec.md](spec.md) | **Date**: 2026-07-14

A runnable end-to-end validation guide for the UUID identifier fix. Use this after the implementation to prove the five success criteria (SC-001 through SC-006 in `spec.md`) hold. Implementation details (migration text, model bodies, test code) live in `tasks.md` and the implementation phase — this file is a validation/run guide only.

## Prerequisites

- Python 3.12, `uv`, and the project's pinned dependencies installed (`uv sync`).
- A local Postgres for the **own DB** (the Testcontainers fixture in `tests/conftest.py` works for the test-driven path; a standalone local Postgres works for the manual path).
- The **backend DB** is NOT required for any validation step here. Read-only access to it is exercised through mocks/fixtures, per Constitution Principle I. The one place this feature reads `Products.title` is tested with a mocked backend session.

## Step 0 — Recover from the migration amendment

Because the own-DB migration `a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py` is amended in place (see `research.md` D2), any environment that already ran the integer-typed version must re-provision:

```bash
# Drop-and-recreate path (simplest; CI uses fresh Testcontainers so is unaffected):
alembic downgrade base     # or: dropdb <own_db> && createdb <own_db>
alembic upgrade head
```

**Expected outcome**: the own DB now has UUID-typed columns. Verify with one query (run via `psql` or the project's DB shell):

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name IN ('ai_audit_log', 'ai_problem_statements', 'ai_recommendation_logs')
  AND column_name IN ('user_id', 'product_id');
```

Every row returned must report `data_type = uuid` (SC-001). This is also asserted by a new Testcontainers integration test (see `tasks.md`).

## Step 1 — Seed problem statements with UUID product IDs

The seed CLI now expects UUID product IDs (see `research.md` D6). Prepare a seed file:

```json
[
  {"product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f", "statement_text": "Need a low-fee savings account"},
  {"product_id": "9f4b2a1c-2d3e-4f5a-8b7c-1d2e3f4a5b6c", "statement_text": "Want a cashback credit card"}
]
```

Run the seed CLI (path documented in `app/features/recommendations/seed.py`):

```bash
uv run python -m app.features.recommendations.seed path/to/seed.json
```

**Expected outcome**: prints `Seeded N problem statements`. The `ai_problem_statements` rows now carry UUID `product_id` values (verifiable with a `SELECT product_id FROM ai_problem_statements;` — values must be UUIDs, not integers).

## Step 2 — Send a chat turn with a UUID `user_id` and verify the audit row

Start the service (with mock LLM mode on so no real model call is needed):

```bash
USE_MOCK_LLM=1 uv run uvicorn app.main:app --reload
```

Send a chat turn:

```bash
curl -N -X POST http://localhost:8000/internal/chat \
  -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
    "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
    "message": "How much did I spend on groceries last month?"
  }'
```

Note: there is no `is_first_turn` field (removed — `research.md` D11) and `initial_context` is omitted here since it carries only optional, identity-unrelated conversation context (e.g. account summary), never `user_id`.

**Expected outcome**: a streamed SSE response with `token` events and one terminal `done` event (the chat-stream contract from spec 009 is unchanged in envelope).

Then verify the audit row:

```sql
SELECT user_id, action, detail_json
FROM ai_audit_log
WHERE action = 'chat_turn'
ORDER BY created_at DESC
LIMIT 1;
```

**Expected outcome**: `user_id` is the UUID you sent (`7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d`), stored natively as a UUID — not an integer, not a stringified integer. This is SC-003.

## Step 2a — Verify multi-turn continuity with no `is_first_turn` flag

Send a second turn on the **same** `conversation_id`, again with no `is_first_turn`:

```bash
curl -N -X POST http://localhost:8000/internal/chat \
  -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
    "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
    "message": "And what about last week?"
  }'
```

**Expected outcome**: the service determines this is a continuing thread by reading the checkpointer directly (`graph.aget_state`), not from a client-supplied flag — `ConversationState.user_id` and any previously-stored `planner_answers`/`stage`/`user_context` for this `conversation_id` are restored automatically. A second `ai_audit_log` row is written for the same UUID (FR-014).

## Step 3 — Verify the audit rejects non-UUID `user_id` (fail-fast)

Repeat Step 2's request with a non-UUID `user_id`:

```bash
curl -X POST http://localhost:8000/internal/chat \
  -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "...", "user_id": 1001, "message": "..."}'
```

**Expected outcome**: HTTP 422, before any stream starts. No audit row is written (Principle VII fail-fast; FR-001).

## Step 4 — Trigger a recommendation reply and verify the real product title

Trigger a recommendation intent from a chat turn (or call `/internal/recommendations/match` directly with a UUID `user_id`). Inspect the terminal `done` event's widget payload:

**Expected outcome**:
- `product_id` is a UUID (canonical hyphenated string) matching one of the seeded UUIDs (SC-004).
- `product_name` is the **real** title from the backend `Products` table (or the documented outage fallback if the backend is mocked as unavailable) — **never** the fabricated `"Product {id}"` placeholder (FR-007).

Then verify the recommendation log:

```sql
SELECT user_id, product_id, matched_query, similarity_score
FROM ai_recommendation_logs
ORDER BY shown_at DESC
LIMIT 3;
```

**Expected outcome**: `user_id` and `product_id` are both UUIDs, matching the request and the matched product respectively (SC-004).

## Step 5 — Verify the analytics examples are no longer misleading

This is a documentation-only check (SC-002). Confirm no integer-like ID examples remain in the public contract:

```bash
rg --type=py '"1001"|"5001"|examples=\[1001\]' app/features/analytics/schemas.py
```

**Expected outcome**: no matches. All ID-shaped examples in `analytics/schemas.py` are realistic UUID strings.

## Step 6 — Run the full automated suite

```bash
uv run pytest
```

**Expected outcome**: all tests pass (SC-005). Specifically:
- Every test that builds a `ChatTurnRequest` or `MatchRequest` uses a UUID `user_id`.
- Every test that asserts a `product_id` value compares against a UUID.
- The new Testcontainers integration test asserts the four amended columns are `Uuid`-typed after `alembic upgrade head`.
- Multi-turn continuity tests (`tests/integration/test_chat_memory.py`) still pass — `ConversationState` gained a root-level `user_id` field and `user_context` reverted to a plain `dict | None` (D11), and turn resumption still works with no `is_first_turn` flag (SC-006, FR-013, FR-014).

## Step 7 — Lint, format, type-check

```bash
uv run ruff check .
uv run black --check .
uv run mypy
```

**Expected outcome**: all three pass. The mypy run is the most important here — the `record_audit` signature change from `int | None` to `UUID | None` should ripple through the three call sites that pass `user_id=None`, and they should all still type-check without further change.

## Cross-references

- Spec & scope: [spec.md](spec.md)
- Design decisions: [research.md](research.md)
- Column / DTO type changes (before/after tables): [data-model.md](data-model.md)
- Contract changes: [contracts/chat-stream-amendment.md](contracts/chat-stream-amendment.md), [contracts/recommendations-match.md](contracts/recommendations-match.md)
