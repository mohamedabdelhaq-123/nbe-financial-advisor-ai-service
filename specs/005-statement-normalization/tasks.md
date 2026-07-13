# Tasks: Statement Transaction Normalization

**Input**: Design documents from `specs/005-statement-normalization/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/ingestion-normalize.md](contracts/ingestion-normalize.md), [quickstart.md](quickstart.md)

**Tests**: Included. Constitution Principle I ("Every feature MUST ship with automated unit and
integration tests") makes tests mandatory for this repository, not optional.

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- File paths are exact and relative to the repository root

## Path Conventions

Single project, existing FastAPI service. New source lives in the existing
`app/features/ingestion/` slice (Part 1's document-processing capability already lives there, per
plan.md's Structure Decision); new tests extend the existing top-level `tests/features/ingestion/`.
See [plan.md](plan.md) Project Structure for the full tree.

---

## Phase 1: Setup

**Purpose**: The new own-DB table this feature needs, created and seeded, before any story-specific code exists.

- [X] T001 [P] Create Alembic migration `migrations/versions/<new-hash>_add_categories_table.py` (`down_revision = "a1b2c3d4e5f6"`, following the existing hand-written `op.create_table(...)` style in `a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py` — no autogeneration): `op.create_table("categories", id (Integer, autoincrement PK), name (String, unique, not null), label (String, not null), is_fallback (Boolean, not null, default False))`, then `op.bulk_insert(...)` seeding groceries, dining, transport, utilities, rent, salary, transfer, fees, entertainment, healthcare, shopping, and `other` (`is_fallback=True`) — exactly one seeded row has `is_fallback=True`
- [X] T002 [P] Create `app/features/ingestion/categories.py` with a `Category(OwnBase)` model whose columns mirror T001's migration exactly (`id`, `name`, `label`, `is_fallback`)

**Checkpoint**: `categories` table is migratable and the ORM model matches it.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared pieces every user story's implementation needs. No story-specific work starts before this phase is done.

**⚠️ CRITICAL**: No User Story phase can begin until this phase is complete.

- [X] T003 [P] Add `async def resolve_category(session: AsyncSession, raw: str | None) -> str` to `app/features/ingestion/categories.py`: case-insensitive exact match of `raw` against `Category.name`; returns the seeded `is_fallback` row's `name` when `raw` is `None`/blank or matches no row (depends on T002)
- [X] T004 [P] Add `import app.features.ingestion.categories  # noqa: F401` to `tests/conftest.py`'s `own_db_url` fixture, alongside the existing `app.features.audit.models` import, so `categories` registers on `OwnBase.metadata` before Testcontainers' `create_all()` runs
- [X] T005 [P] Define `NormalizeStatementRequest` (`ocr_result_id: UUID`) and `NormalizeStatementResult` (`normalized_json: dict`, `model_used: str`) in `app/features/ingestion/schemas.py`, per [contracts/ingestion-normalize.md](contracts/ingestion-normalize.md)
- [X] T006 Add a `POST /normalize` handler stub to `app/features/ingestion/router.py` that calls `service.normalize_statement(...)` (stub the service call — full wiring lands in US1's implementation task) (depends on T005)

**Checkpoint**: Category infra exists and is independently testable; the normalize route exists, auth-guarded, behind a stub.

---

## Phase 3: User Story 1 - Extract structured transactions from a processed statement (Priority: P1) 🎯 MVP

**Goal**: Given a `StatementOcrResult` id, produce a full normalized result (bank name, account hint, categorized transaction list) and return it, persisting `normalized.json` alongside Part 1's artifacts.

**Independent Test**: Call the normalize endpoint (or `normalize_statement()` directly) for a known `StatementOcrResult` id backed by real OCR artifacts, and confirm the response contains a well-formed transaction list (each entry carrying a seeded category) and a model identifier; confirm every documented failure mode (unknown id, unreadable artifacts, LLM failure, no-transactions content) behaves per contract.

### Tests for User Story 1 ⚠️

> Write these first; they must fail before the corresponding implementation task below.

- [X] T007 [P] [US1] In `tests/features/ingestion/test_categories.py`: test `resolve_category()` against the real Testcontainers `own_pg` fixture — exact match, case-insensitive match, and fallback for an unmatched/`None` value (depends on T001, T003, T004)
- [X] T008 [P] [US1] In `tests/features/ingestion/test_normalizer.py`: test the LLM-parsing function with fixture `content_list`/`markdown` input and a mock-mode response — assert the parsed `{bank_name, account_hint, transactions[]}` shape, and that a transaction missing a confidently-determinable date/amount is omitted from the list (spec Edge Cases) rather than included malformed
- [X] T009 [P] [US1] In `tests/features/ingestion/test_service.py`: happy-path test — a fake `StatementOcrResult`/`StatementFiles` lookup, a fake storage client (existing `markdown.md`/`content_list.json` to read, captures the `normalized.json` write), a monkeypatched normalizer call returning a fixed parsed result, and the real Testcontainers `own_pg` session for category resolution + audit — assert the returned `NormalizeStatementResult` and that every transaction's `category` is one of the seeded values
- [X] T010 [P] [US1] In `tests/features/ingestion/test_service.py`: unknown `ocr_result_id` (well-formed UUID, no matching row) → `HTTPException(404)`, and neither the storage client nor the normalizer is ever invoked
- [X] T011 [P] [US1] In `tests/features/ingestion/test_service.py`: OCR artifacts missing/unreadable in storage → `HTTPException(502)` whose detail identifies a source-retrieval failure
- [X] T012 [P] [US1] In `tests/features/ingestion/test_service.py`: the normalizer call raising or returning unparseable output → `HTTPException(502)` whose detail identifies a processing failure, and confirm nothing is persisted (no storage write, no audit row)
- [X] T013 [P] [US1] In `tests/features/ingestion/test_service.py`: OCR content with no identifiable transactions → a successful result with `transactions: []` (FR-015), not an error
- [X] T014 [P] [US1] In `tests/features/ingestion/test_router.py`: extend with the normalize endpoint — `401` without a bearer token, `200` with a mocked `service.normalize_statement`, and `422` on a malformed `ocr_result_id`

### Implementation for User Story 1

- [X] T015 [US1] In `app/features/ingestion/normalizer.py`: implement `async def extract_normalized_content(content_list: list, markdown: str) -> tuple[dict, str]` — `if settings.use_mock_llm:` return a small fixed deterministic result (mirroring `plan/service.py::_mock_plan()`'s approach); else build a prompt from `content_list`'s entries (primary source — research.md §1) plus `markdown` (fallback context) instructing the model to return ONLY a JSON object matching the spec's shape, call `app.core.llm.get_chat_model().ainvoke(prompt)`, and tolerantly parse the JSON response (a rescue pattern mirroring `plan/service.py::_parse_and_normalize()`), omitting any transaction entry missing a confidently-determined date/amount; return `(parsed_dict, settings.model_name)` — makes T008 pass
- [X] T016 [US1] In `app/features/ingestion/service.py`: implement `async def normalize_statement(session_gen, own_session_gen, ocr_result_id: str) -> NormalizeStatementResult` — look up `StatementOcrResult` by id first, raising `HTTPException(404, "ocr result not found")` immediately if missing before any I/O (makes T010 pass); resolve its `statement_id`; read `markdown.md` and `content_list.json` from `{settings.storage_s3_ocr_bucket}/{statement_id}/` wrapped in `try/except` → `HTTPException(502, "failed to retrieve OCR content: ...")` (makes T011 pass); call `normalizer.extract_normalized_content(...)` wrapped in `try/except` → `HTTPException(502, "normalization engine failed: ...")`, distinct from the retrieval message (makes T012 pass); for each transaction, resolve its category via `categories.resolve_category()` against a session from `own_session_gen()`; set `duplicate_of: None` on every transaction for now (US2 wires real matching); assemble the full `normalized_json` (allowing an empty `transactions` list to pass through as a success — makes T013 pass); write it to `{bucket}/{statement_id}/normalized.json`; record one audit row (`action="ingestion.normalize"`, detail `{"statement_id", "ocr_result_id", "prefix"}`) + explicit `await own_session.commit()` (same pattern as Part 1's `process_statement()`); return `NormalizeStatementResult(normalized_json=..., model_used=...)` — makes T009 pass (depends on T015)
- [X] T017 [US1] Wire `POST /internal/ingestion/normalize` in `app/features/ingestion/router.py` to call `service.normalize_statement(session_gen=get_backend_session, own_session_gen=get_own_session, ocr_result_id=str(body.ocr_result_id))`, replacing the Phase 2 stub — makes T014 pass (depends on T016)

**Checkpoint**: User Story 1 is fully functional and independently testable — the normalize endpoint works end-to-end in mock mode, categories always resolve to a seeded value, and every documented failure mode is enforced. `duplicate_of` is `null` for every transaction until US2 lands.

---

## Phase 4: User Story 2 - Flag likely duplicate transactions (Priority: P2)

**Goal**: Each extracted transaction is checked against the user's existing recorded transactions and flagged with a reference when a likely duplicate is found.

**Independent Test**: Normalize a statement for a user who already has a matching existing transaction (same amount, date within 2 days); confirm that entry's `duplicate_of` is the existing row's id, while non-matching entries have `duplicate_of: null`.

### Tests for User Story 2 ⚠️

- [X] T018 [P] [US2] In `tests/features/ingestion/test_normalizer.py`: test `find_duplicate()` — given a fake backend session returning existing `Transactions` rows for a user, assert an exact-amount + within-2-day match returns that row's `id`; assert the closest-by-date candidate wins when more than one matches; assert `None` when no candidate matches or the user has no existing rows
- [X] T019 [P] [US2] In `tests/features/ingestion/test_service.py`: full-flow test where the mocked backend session returns existing transactions for the statement's user — assert the resulting `normalized_json`'s matching transaction has `duplicate_of` set to the existing row's id, and its non-matching entries have `duplicate_of: null`

### Implementation for User Story 2

- [X] T020 [US2] In `app/features/ingestion/normalizer.py`: implement `async def find_duplicate(session, user_id: uuid.UUID, transaction_date: date, amount: Decimal) -> str | None` — selects only `id`, `transaction_date`, `amount` from `Transactions` (Constitution III egress minimization) filtered by `user_id` (not `account_id` — may not be linked yet, research.md §4) and `amount`, with `transaction_date` within a 2-day window; returns the closest match's `id` as a string, or `None` — makes T018 pass
- [X] T021 [US2] In `app/features/ingestion/service.py`: wire `find_duplicate()` into `normalize_statement()` — for each transaction with a determinable date/amount, query it (using the statement's `user_id`, resolved via `StatementFiles`) against the backend session and set `duplicate_of` accordingly — makes T019 pass (depends on T020, extends T016)

**Checkpoint**: User Stories 1 AND 2 both work independently — duplicate flagging is functional and verified.

---

## Phase 5: User Story 3 - Consistent transaction categorization (Priority: P2)

**Goal**: Every extracted transaction's category is drawn from the maintained category list, with a designated fallback for anything that doesn't clearly match, and the LLM is steered toward the known list rather than relying on post-hoc lookup alone.

**Independent Test**: Normalize statements with varied merchant text and confirm every returned transaction's category is one of the maintained list's values, including cases where the LLM's raw output doesn't cleanly match any seeded name.

### Tests for User Story 3 ⚠️

- [X] T022 [P] [US3] In `tests/features/ingestion/test_service.py`: full-flow test where the (mock-mode) normalizer produces a category string that doesn't match any seeded `Category.name` — assert the resulting transaction's `category` is the seeded fallback value, not the raw unmatched string
- [X] T023 [P] [US3] In `tests/features/ingestion/test_categories.py`: assert `resolve_category()` given differently-cased input for the same known category (e.g. `"Groceries"` vs `"groceries"`) resolves to the identical stored `name`

### Implementation for User Story 3

- [X] T024 [US3] In `app/features/ingestion/normalizer.py`/`service.py`: fetch the current `Category.name`/`label` values (via `own_session_gen()`) before building the LLM prompt in `extract_normalized_content()`, and inject the known list into the prompt so the model is instructed to choose from those exact names — refines T015/T016 for better first-pass accuracy; `resolve_category()`'s fallback (T003) still guarantees a known value regardless — makes T022 meaningfully exercised end-to-end

**Checkpoint**: User Stories 1, 2, AND 3 all work independently — categorization is consistent, prompt-informed, and always resolves to a known value.

---

## Phase 6: User Story 4 - Normalized result durably persisted for audit and reuse (Priority: P3)

**Goal**: The object written to storage and the result returned to the caller are guaranteed to match, including across re-normalization of the same statement.

**Independent Test**: Request normalization, then independently read the resulting object back from storage and confirm it matches the returned result byte-for-byte; request it a second time and confirm the object is overwritten rather than duplicated under a new key.

### Tests for User Story 4 ⚠️

- [X] T025 [P] [US4] In `tests/features/ingestion/test_service.py`: after a successful `normalize_statement()` call, assert the captured `put_object` body at `{bucket}/{statement_id}/normalized.json` deserializes to exactly the same dict as the returned `NormalizeStatementResult.normalized_json`
- [X] T026 [P] [US4] In `tests/features/ingestion/test_service.py`: call `normalize_statement()` twice for the same `ocr_result_id`; assert `put_object` is invoked a second time against the same key (overwrite semantics — spec Assumptions), not a new key

### Implementation for User Story 4

- [X] T027 [US4] In `app/features/ingestion/service.py`: confirm/adjust `normalize_statement()` so the object written to storage and the dict returned to the caller are built from one shared value, never two independently-assembled dicts that could drift apart — makes T025/T026 pass

**Checkpoint**: All four user stories are independently functional; every documented behavior in [contracts/ingestion-normalize.md](contracts/ingestion-normalize.md) is enforced and tested.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T028 [P] Run Ruff, `black --check`, and `mypy` across all new/changed files (`migrations/versions/<new-hash>_add_categories_table.py`, `app/features/ingestion/**`, `tests/conftest.py`) and fix any violations
- [X] T029 [P] Run the offline unit-test steps of [quickstart.md](quickstart.md) end-to-end (`pytest tests/features/ingestion/ -v`) and confirm all pass
- [ ] T030 Run the real-LLM steps of [quickstart.md](quickstart.md) against the configured `OPENAI_BASE_URL`/`MODEL_NAME`, and record any prompt/parsing discrepancy back into [research.md](research.md) §2/§3 (mirrors Part 1's real-engine validation task)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; extends US1's `service.py`/`normalizer.py`, so start after US1's implementation tasks land, not just after Foundational
- **User Story 3 (Phase 5)**: Depends on Foundational; refines the same `normalizer.py`/`service.py` prompt-building built in US1 — implement after T016 exists
- **User Story 4 (Phase 6)**: Depends on Foundational; verifies/hardens the same `service.py` persistence path — implement after T016 (and ideally after US2/US3, so the verified object includes `duplicate_of`/prompt-informed categories) though it does not strictly require them
- **Polish (Phase 7)**: Depends on all four user stories being complete

### User Story Dependencies

- **US1 (P1)**: No dependency on US2/US3/US4; independently testable as soon as Foundational is done
- **US2 (P2)**: Extends the same `normalizer.py`/`service.py` files US1 creates — sequenced after US1's implementation, despite being a separate story
- **US3 (P2)**: Extends the same files again — sequenced after US1 (independent of US2's dedup logic, though implementing after US2 avoids touching the same prompt-building code twice in flight)
- **US4 (P3)**: Extends the same files a final time — sequenced last for the cleanest verification of the fully-assembled result

### Within Each User Story

- Tests are written first and must fail before the paired implementation task
- `normalizer.py` changes precede the `service.py` changes that consume them
- `service.py` changes precede the `router.py` wiring that exposes them (US1 only; US2–US4 don't touch `router.py`)

### Parallel Opportunities

- T001, T002 (Setup) can run in parallel
- T003, T004, T005 (Foundational) can run in parallel; T006 depends on T005
- Within US1: T007–T014 (all different test files/cases) can run in parallel with each other
- Within US2: T018, T019 can run in parallel with each other, but not with US1's implementation tasks (they extend the same files)
- Within US3: T022, T023 can run in parallel with each other
- Within US4: T025, T026 can run in parallel with each other
- T028, T029 (Polish) can run in parallel; T030 is sequential (a live, manual validation run)

---

## Parallel Example: User Story 1

```bash
# Launch the test-writing tasks for User Story 1 together:
Task: "Write test_categories.py resolve_category() tests"
Task: "Write test_normalizer.py extraction-parsing tests"
Task: "Write test_service.py happy-path + all four failure-mode tests"
Task: "Write test_router.py auth + happy-path + 422 tests"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: run `pytest tests/features/ingestion/` — happy-path normalization + every documented failure mode works independently
5. This is a legitimate MVP: a caller already gets a fully-shaped, categorized `normalized_json` at a known location; duplicate flagging, prompt-informed categorization, and persistence-consistency hardening land next

### Incremental Delivery

1. Setup + Foundational → categories table + schemas + stub route ready
2. Add US1 → validate independently → MVP
3. Add US2 → validate independently → duplicate flagging
4. Add US3 → validate independently → prompt-informed categorization
5. Add US4 → validate independently → persistence-consistency guarantees hardened
6. Polish → lint/type-check clean, full quickstart validated against a real LLM

---

## Notes

- [P] tasks touch different files (or independent test cases in the same file) with no unmet dependency
- [Story] labels map every story-phase task to spec.md's US1/US2/US3/US4 for traceability
- US2, US3, and US4 are not fully independent of US1 at the *file* level (they extend
  `normalizer.py`/`service.py` rather than adding new files) — they remain independent at the
  *behavioral/test* level, per their own Independent Test criteria, matching Part 1's precedent
  (see `specs/004-document-processor/tasks.md` Notes)
- Commit after each task or logical group
- Avoid: vague tasks, unnecessary same-file conflicts, skipping a story's tests before its implementation
