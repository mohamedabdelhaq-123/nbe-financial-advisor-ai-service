---

description: "Task list for Transaction Embedding by ID"
---

# Tasks: Transaction Embedding by ID

**Input**: Design documents from `/specs/008-embed-transactions/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/transactions-embed.md](./contracts/transactions-embed.md), [quickstart.md](./quickstart.md)

**Tests**: Included and REQUIRED — Constitution Principle I mandates automated unit
and integration tests for every feature, with integration tests against a real
Postgres (Testcontainers). This is a single-endpoint feature: User Stories 1–3 are
different scenarios of the *same* atomic code path (FR-006/FR-010 require the
existence-check, the write, and the overwrite behavior to live in one transaction),
so Phase 2 (Foundational) implements the endpoint completely, and each user-story
phase below adds that story's test coverage against the already-built
implementation — still independently runnable per story, per spec.md's
"Independent Test" for each.

**Organization**: Tasks are grouped by user story so each story's test coverage can
be run and reviewed independently, per Constitution Principle V's vertical-slice
convention (`app/features/transactions/`, mirroring `embed`/`analytics`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Tasks that add multiple test functions to the same file are listed sequentially
  (not `[P]`) even across stories, since concurrent edits to one file conflict.

## Path Conventions

Single project, existing layout: `app/features/<slice>/`, `tests/features/<slice>/`
(see [plan.md](./plan.md)'s Project Structure — no new top-level directories).

---

## Phase 1: Setup

**Purpose**: Scaffold the new feature slice (Constitution Principle V — no new
dependencies needed; everything this feature reuses — FastAPI, SQLAlchemy,
`embed_texts`, `record_audit` — is already in the project).

- [X] T001 Create the `app/features/transactions/` feature slice skeleton: `__init__.py` (module docstring), empty `router.py`, `schemas.py`, `service.py`
- [X] T002 [P] Create `tests/features/transactions/__init__.py`

**Checkpoint**: Slice scaffolding exists; ready for foundational implementation.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement the endpoint end-to-end. This is the shared core every user
story's tests exercise — the all-or-nothing atomicity (FR-006, FR-010) means
"embed valid IDs" and "reject invalid IDs" are two branches of one transaction,
not separable increments.

**⚠️ CRITICAL**: No user-story test phase can start until this phase is complete.

- [X] T003 In `app/features/transactions/schemas.py`, define `TransactionEmbedRequest` (`transaction_ids: list[UUID]`, validated via a `field_validator` to 1–500 unique entries — deduplicate while preserving first occurrence, reject empty and reject over 500 with a clear message per FR-004/FR-013, raised as `ValueError` so FastAPI surfaces it as 422 — matching `/internal/embeddings`'s existing blank-input validator, not a hand-written 400 branch, per [contracts/transactions-embed.md](./contracts/transactions-embed.md)), `TransactionEmbedResult` (`transaction_id: UUID`, `status: Literal["embedded"]`), and `TransactionEmbedResponse` (`results: list[TransactionEmbedResult]`)
- [X] T004 In `app/features/transactions/service.py`, implement `_build_summary_text(transaction) -> str`: one line combining merchant (prefer `merchant_normalized`, fall back to `merchant_raw`), `category`, `amount`, `currency`, `transaction_date`, per the clarified FR-003 structured-summary decision (see [research.md](./research.md))
- [X] T005 In `app/features/transactions/service.py`, define `class TransactionsNotFoundError(Exception)` carrying `invalid_transaction_ids: list[UUID]`
- [X] T006 In `app/features/transactions/service.py`, implement `async def embed_transactions(session_gen, own_session_gen, transaction_ids: list[UUID], embed_fn=None) -> list[UUID]` (depends on T004, T005): open one backend DB transaction via `session_gen()`; `SELECT` all requested `Transaction` rows by ID; if any ID is missing, raise `TransactionsNotFoundError` without issuing any write (FR-006); otherwise execute `SET TRANSACTION READ WRITE` (per [research.md](./research.md) — the `ai_readonly` role's `default_transaction_read_only=on` default requires this override, scoped to this one transaction), call `embed_fn` (default `app.features.embed.service.embed_texts`, imported lazily like `compute_monthly_summary` does) once with every built summary and `dimensions=TRANSACTION_EMBEDDING_DIM` from `app.backend_db.models`, `UPDATE` each row's `embedding` and no other column (FR-005), and commit only after every row is updated (FR-010); return the list of embedded transaction IDs
- [X] T007 In `app/features/transactions/service.py`, extend `embed_transactions` (depends on T006) to call `record_audit` (from `app.core.audit`) via `own_session_gen()` — `action="transactions.embed"`, `detail={"transaction_ids": [str(i) for i in transaction_ids]}` — immediately after the backend transaction commits successfully, then `await own_session.commit()` (FR-012, matching the explicit-commit pattern in `app/features/ingestion/service/process.py`)
- [X] T008 In `app/features/transactions/router.py`, implement `POST /internal/transactions/embed` under `APIRouter(prefix="/internal/transactions", tags=["transactions"], dependencies=[Depends(require_token)])` (depends on T003, T006, T007): wrap `get_backend_session`/`get_own_session` with `asynccontextmanager(...)` into module-level `_backend_session_gen`/`_own_session_gen` adapters — mirroring `app/features/analytics/router.py`'s documented `_backend_session_gen = asynccontextmanager(get_backend_session)` workaround, since `embed_transactions` (T006) expects `async with session_gen()`, not a plain FastAPI async-generator dependency — and pass those into `embed_transactions`; catch `TransactionsNotFoundError` → `HTTPException(404, detail={"message": "One or more transaction IDs were not found", "invalid_transaction_ids": [...]})` (per [contracts/transactions-embed.md](./contracts/transactions-embed.md) — note FastAPI nests this one level under a top-level `"detail"` key, do not add a duplicate inner `"detail"` key); catch any other exception → `HTTPException(502, detail="Embedding provider unavailable")` (matching `app/features/embed/router.py`'s pattern); on success return `TransactionEmbedResponse` with one `"embedded"` result per requested ID
- [X] T009 In `app/main.py`, import the `transactions` router module and add `app.include_router(transactions.router)`

**Checkpoint**: `POST /internal/transactions/embed` is fully implemented. User-story phases below add test coverage; no further implementation changes are expected unless a test reveals a defect.

---

## Phase 3: User Story 1 - Backend requests embeddings for newly ingested transactions (Priority: P1) 🎯 MVP

**Goal**: Prove the core happy path — valid, never-embedded transaction IDs get embedded and persisted; auth is enforced; malformed batches are rejected before anything runs.

**Independent Test**: Run `tests/features/transactions/test_transactions_service.py` and `tests/features/transactions/test_transactions_router.py`'s US1 tests in isolation (no US2/US3 test needs to exist or pass).

- [X] T010 [P] [US1] In `tests/features/transactions/test_transactions_service.py`, using the `own_pg` fixture (seed `transactions` rows via raw SQL as in `tests/features/analytics/test_monthly_summary.py`): call `embed_transactions` with a batch of valid, never-embedded transaction IDs; assert every row's `embedding` column is now a non-null vector of length `TRANSACTION_EMBEDDING_DIM`, and that a single-ID batch also succeeds
- [X] T011 [P] [US1] In `tests/features/transactions/test_transactions_router.py`, using the `client`/`auth_headers` fixtures: assert `POST /internal/transactions/embed` without a Bearer token returns 401 and writes nothing; assert a request with a mocked `app.features.transactions.router.embed_transactions` (monkeypatched, matching `tests/features/ingestion/test_router.py`'s pattern) returns 200 with one `"embedded"` result per requested ID
- [X] T012 [US1] In `tests/features/transactions/test_transactions_router.py` (same file as T011 — sequential): assert an empty `transaction_ids` list and a 501-ID list are both rejected by the real endpoint with exactly **422** (no mocking needed — Pydantic validation from T003 runs before the route handler, and thus before any DB/embedding call, exactly like `/internal/embeddings`'s `test_embeddings_422_empty_input_list`); then, with `embed_transactions` mocked as in T011 (avoiding any real backend DB dependency), assert a request of exactly 500 IDs is NOT rejected by validation (reaches the mocked service and returns 200) — the at-limit boundary, complementing the 501 over-limit case

**Checkpoint**: User Story 1 is fully functional and independently testable — this is the MVP.

---

## Phase 4: User Story 2 - Backend re-embeds existing transactions (Priority: P2)

**Goal**: Re-embedding a transaction that already has a stored embedding overwrites it rather than duplicating or rejecting.

**Independent Test**: Run the US2 test in `test_transactions_service.py` alone; it seeds its own already-embedded row and does not depend on US1's or US3's test data.

- [X] T013 [US2] In `tests/features/transactions/test_transactions_service.py` (same file as T010 — sequential): seed a transaction with a pre-existing, non-null `embedding` value; call `embed_transactions` again for that ID; assert the stored `embedding` changes to a new value (not left unchanged, not duplicated) and the call still succeeds (FR-007)

**Checkpoint**: User Stories 1 AND 2 both work independently.

---

## Phase 5: User Story 3 - Backend gets a clear, actionable rejection for an invalid batch (Priority: P3)

**Goal**: A batch with any invalid ID, or a mid-batch provider failure, writes nothing at all (all-or-nothing, FR-006/FR-010) and reports specifically what went wrong.

**Independent Test**: Run the US3 tests alone; each seeds exactly the rows it needs and asserts on their state after the call, independent of US1/US2 test data.

- [X] T014 [US3] In `tests/features/transactions/test_transactions_service.py` (same file as T010/T013 — sequential): seed one existing transaction, call `embed_transactions` with that ID plus a nonexistent UUID; assert `TransactionsNotFoundError.invalid_transaction_ids` names exactly the nonexistent one, and that the existing row's `embedding` is still unchanged afterward (nothing written for either ID)
- [X] T015 [US3] In `tests/features/transactions/test_transactions_service.py` (same file — sequential): seed valid transactions, pass an `embed_fn` that raises (simulating a provider outage) into `embed_transactions`; assert the exception propagates and every seeded row's `embedding` is unchanged (no partial writes, FR-010)
- [X] T016 [P] [US3] In `tests/features/transactions/test_transactions_router.py` (different file than T014/T015 — parallelizable): with `embed_transactions` monkeypatched to raise `TransactionsNotFoundError(["<uuid>"])`, assert the endpoint returns 404 with body exactly `{"detail": {"message": "...", "invalid_transaction_ids": ["<uuid>"]}}` (per [contracts/transactions-embed.md](./contracts/transactions-embed.md)'s corrected, FastAPI-accurate shape — not a flat body); with it monkeypatched to raise a generic exception, assert 502

**Checkpoint**: All three user stories are independently functional and tested.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verifications that span every scenario above, plus repo hygiene.

- [X] T017 In `tests/features/transactions/test_transactions_service.py` (sequential, same file): assert exactly one `ai_audit_log` row is written per successful `embed_transactions` call, with `action="transactions.embed"` and `detail_json` listing the requested transaction IDs (FR-012) — and zero rows are written when the call fails (T014/T015's scenarios)
- [X] T018 In `tests/features/transactions/test_transactions_service.py` (sequential, same file): across a success case and a rejection case, assert no column other than `embedding` ever changes on a targeted transaction row (SC-004) — compare every other field before/after
- [X] T019 [P] Update the module docstring in `app/backend_db/__init__.py`, which currently states "the application defines no write paths against this Base," to note the one narrow, constitution-authorized exception this feature adds (`transactions.embedding`, via `app.features.transactions.service.embed_transactions`), keeping the statement accurate per Constitution v2.2.0's Principle IV
- [X] T020 Run `uv run ruff check .`, `uv run black --check .`, `uv run mypy .`, and the [quickstart.md](./quickstart.md) manual smoke test end-to-end; confirm all pass before merge

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user story phases (T003→T004/T005→T006→T007→T008→T009, strictly sequential within the phase since T004–T008 all touch `service.py`/`router.py`)
- **User Stories (Phase 3–5)**: All depend on Foundational completion; may proceed in priority order or, across different test files, in parallel
- **Polish (Phase 6)**: Depends on Phase 3–5 completion (needs the scenarios they establish to already be passing)

### User Story Dependencies

- **User Story 1 (P1)**: No dependency on US2/US3 test data
- **User Story 2 (P2)**: Independent of US1/US3 test data (seeds its own row), though its test function is appended to the same file as US1's
- **User Story 3 (P3)**: Independent of US1/US2 test data (seeds its own rows)

### Within Each Phase

- Schema before service (T003 before T004–T007)
- Service before router (T006/T007 before T008)
- Router before registration (T008 before T009)
- Implementation (Phase 2) before any test phase

---

## Parallel Example: across Phase 3

```bash
# T010 (test_transactions_service.py) and T011 (test_transactions_router.py) touch
# different files and can be worked on in parallel; T012 must follow T011 (same file).
Task: "Integration test — fresh-embed happy path in tests/features/transactions/test_transactions_service.py"
Task: "Router test — 401 + mocked 200 happy path in tests/features/transactions/test_transactions_router.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (the whole endpoint — required before any story is testable)
3. Complete Phase 3: User Story 1 (T010–T012)
4. **STOP and VALIDATE**: run `tests/features/transactions/` and the quickstart.md manual smoke test
5. Deploy/demo if ready — a single valid batch can already be embedded end-to-end

### Incremental Delivery

1. Setup + Foundational → endpoint exists, unproven
2. Add US1 tests → prove the happy path → MVP demo-able
3. Add US2 test → prove re-embedding is safe
4. Add US3 tests → prove all-or-nothing failure handling
5. Polish → audit-log and no-collateral-write guarantees confirmed, docs/lint/type-check clean

---

## Notes

- [P] tasks touch different files with no dependency on an incomplete task
- [Story] labels map each test task to the spec.md user story it proves
- Because Phase 2 implements the whole endpoint up front (see the Tests note above), "story implementation" tasks don't reappear per story — only that story's tests do
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently
