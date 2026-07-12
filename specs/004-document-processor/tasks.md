# Tasks: Statement Document Processor

**Input**: Design documents from `specs/004-document-processor/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/ingestion-process.md](contracts/ingestion-process.md), [quickstart.md](quickstart.md)

**Tests**: Included. Constitution Principle I ("Every feature MUST ship with automated unit and
integration tests") makes tests mandatory for this repository, not optional.

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths are exact and relative to the repository root

## Path Conventions

Single project, existing FastAPI service. New source lives under `app/features/ingestion/`
(feature-bounded vertical slice, matching every other slice in `app/features/`); new tests live
under the top-level `tests/features/ingestion/`, matching every other slice's test location (not
colocated under `app/features/ingestion/tests/`). See [plan.md](plan.md) Project Structure for the
full tree.

---

## Phase 1: Setup

**Purpose**: Configuration and package scaffolding needed before any story-specific code exists.

- [X] T001 Add `mineru_api_url: str = ""`, `mineru_api_key: str = ""`, `use_mock_mineru: bool = False`, and `storage_s3_ocr_bucket: str = "pfm-statements-ocr"` to `app/core/config.py` (names match the existing `.env.example` entries — no renaming), plus a fail-fast check (mirroring the existing `openai_api_key`/`use_mock_llm` block) that raises `RuntimeError` at import time when `use_mock_mineru` is `False` and `mineru_api_url` is empty
- [X] T002 [P] Update `.env.example`: keep the existing `MINERU_API_URL`/`MINERU_API_KEY` lines as-is, and add `USE_MOCK_MINERU=1` and `STORAGE_S3_OCR_BUCKET=pfm-statements-ocr`
- [X] T003 [P] Create `app/features/ingestion/__init__.py` and `tests/features/ingestion/__init__.py` (empty package scaffolding)

**Checkpoint**: Config settings exist and are readable via `app.core.config.settings`; the `ingestion` package is importable.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared pieces every user story's implementation needs. No story-specific work starts before this phase is done.

**⚠️ CRITICAL**: No User Story phase can begin until this phase is complete.

- [X] T004 ~~Implement a new audit-write function~~ — superseded during implementation: `app.core.audit.record_audit(session, *, user_id, action, detail)` already exists and is already used by `chat/service.py`; no new file needed. Note `record_audit()` only flushes (never commits) — call sites needing durable persistence must commit explicitly themselves
- [X] T005 [P] Define `ProcessStatementRequest` (`statement_id: str`) and `ProcessStatementResult` (`prefix: str`, `ocr_engine: str`) in `app/features/ingestion/schemas.py`, per [contracts/ingestion-process.md](contracts/ingestion-process.md)
- [X] T006 Create `app/features/ingestion/router.py`: `APIRouter(prefix="/internal/ingestion", tags=["ingestion"], dependencies=[Depends(require_token)])` with a `POST /process` handler that calls `service.process_statement(...)` (stub the service call — full wiring lands in US1's implementation task)
- [X] T007 Register the ingestion router in `app/main.py`: `from app.features.ingestion import router as ingestion` and `app.include_router(ingestion.router)`, matching how `analytics`/`plan`/`recommendations` are already registered

**Checkpoint**: Foundation ready — `POST /internal/ingestion/process` exists (returning a stub), auth is enforced, and the audit-write helper is available for User Story 2.

---

## Phase 3: User Story 1 - Extract content from an uploaded statement (Priority: P1) 🎯 MVP

**Goal**: Given a `statement_id`, produce extracted markdown + structured content-list content via MinerU and return where it now lives.

**Independent Test**: Using a test double implementing the `MineruClient` protocol (see below —
`MockMineruClient` itself is deferred past this feature, research.md §8), call the service function
directly (or via the router with a mocked backend session) for a known statement reference and
confirm a `ProcessStatementResult` with a non-empty `prefix` and `ocr_engine == "MinerU"` is
returned, and that `markdown.md`/`content_list.json` were written to storage.

### Tests for User Story 1 ⚠️

> Write these first; they must fail before the corresponding implementation task below.

- [X] T008 [P] [US1] In `tests/features/ingestion/test_mineru_client.py`: test the pure ZIP-extraction helper directly (not the HTTP call) — given a synthetic ZIP fixture (containing a `.md` file and a `content_list.json`), assert it correctly extracts both by file extension into a `ParsedDocument`
- [X] T009 [P] [US1] In `tests/features/ingestion/test_service.py`: happy-path test with a mocked `session_gen` (returns a fake `StatementFiles` row with a well-formed `seaweed_file_id`), a mocked `get_storage_backend` (captures `get_object`/`put_object` calls), and a local test double implementing the `MineruClient` protocol (injected by monkeypatching `get_mineru_client`) that returns markdown + a content list preserving tabular structure (e.g. a row with multiple columns). Assert the returned `prefix`/`ocr_engine`, and that `markdown.md` and `content_list.json` were written under that prefix with the tabular structure intact (spec US1 AC2)
- [X] T010 [P] [US1] In `tests/features/ingestion/test_router.py`: test that `POST /internal/ingestion/process` returns `401` without a bearer token, and `200` with a mocked `service.process_statement` returning a valid `ProcessStatementResult`

### Implementation for User Story 1

- [X] T011 [US1] In `app/features/ingestion/mineru_client.py`: define a `ParsedDocument` shape (markdown, content_list, images), a `MineruClient` `Protocol` with `async def parse_document(self, file_bytes: bytes, filename: str) -> ParsedDocument`, and a pure `_extract_artifacts_from_zip(zip_bytes: bytes) -> ParsedDocument` helper that extracts the markdown file and `content_list.json` by file extension (not assumed fixed paths — research.md §1) — makes T008 pass
- [X] T012 [US1] In `app/features/ingestion/mineru_client.py`: implement `HttpMineruClient` (the real `MineruClient`), whose `parse_document()` opens a fresh `httpx.AsyncClient` (connect timeout ~10s, read timeout ~120s) as an async context manager, `POST {settings.mineru_api_url}/file_parse` multipart with `response_format_zip=true`, `return_md=true`, `return_content_list=true`, `lang_list=["arabic"]`, and header `X-Api-Key: {settings.mineru_api_key}` only when the key is non-empty, then delegates to `_extract_artifacts_from_zip()`; add `get_mineru_client() -> MineruClient` factory that constructs `HttpMineruClient()` (the `settings.use_mock_mineru` branch is a no-op/TODO until `MockMineruClient` exists — see the deferred follow-up task) (depends on T011)
- [X] T013 [US1] Implement `process_statement(session_gen, statement_id: str) -> ProcessStatementResult` in `app/features/ingestion/service.py`: `async with session_gen() as session:` query `StatementFiles` by `uuid.UUID(statement_id)`; split `seaweed_file_id` on the first `/` into `(source_bucket, source_key)`; `async with get_storage_backend() as s3:` fetch the source bytes via `get_object(Bucket=source_bucket, Key=source_key)`; call `get_mineru_client().parse_document(...)` — never call `HttpMineruClient` directly; write `markdown.md` and `content_list.json` to `settings.storage_s3_ocr_bucket` under key prefix `f"{statement_id}/"`; return `ProcessStatementResult(prefix=f"{settings.storage_s3_ocr_bucket}/{statement_id}/", ocr_engine="MinerU")` — makes T009 pass (depends on T012)
- [X] T014 [US1] Wire `POST /internal/ingestion/process` in `app/features/ingestion/router.py` to call `service.process_statement(session_gen=get_backend_session, statement_id=body.statement_id)` and return the result, replacing the Phase 2 stub — makes T010 pass (depends on T013)

**Checkpoint**: User Story 1 is fully functional and independently testable — happy-path extraction with minimal (markdown + content-list) persistence works end-to-end in mock mode.

---

## Phase 4: User Story 2 - Persist extracted artifacts durably, without touching backend records (Priority: P2)

**Goal**: All three artifact kinds (markdown, content list, images) are durably persisted, and the capability is verified to make zero writes to any backend-owned table while recording its own privileged action.

**Independent Test**: Process a statement whose source document contains at least one image; confirm `markdown.md`, `content_list.json`, and one or more `images/<name>` objects all exist under the returned prefix, that the read-only backend session issued only a `SELECT`, and that exactly one `ai_audit_log` row was created for the call.

### Tests for User Story 2 ⚠️

- [X] T015 [P] [US2] Extend `tests/features/ingestion/test_mineru_client.py`: given a ZIP fixture that also contains image files, assert `_extract_artifacts_from_zip()` returns a `name -> bytes` mapping for each image found
- [X] T016 [P] [US2] Extend `tests/features/ingestion/test_service.py`: assert each image artifact is written under `f"{statement_id}/images/{name}"`; assert the mocked backend session records only a `SELECT` (no `INSERT`/`UPDATE`/`DELETE` issued against it — spec SC-005); using the existing `own_pg`/Testcontainers fixture (see `tests/conftest.py`), assert exactly one `ai_audit_log` row is created with `action="ingestion.process"` and `detail_json` containing the processed `statement_id` and returned `prefix`

### Implementation for User Story 2

- [X] T017 [US2] Extend `_extract_artifacts_from_zip()` in `app/features/ingestion/mineru_client.py` to also extract image files from the ZIP (any file not matching the markdown/`content_list.json` names) into a `name -> bytes` dict — makes T015 pass
- [X] T018 [US2] Extend `process_statement()` in `app/features/ingestion/service.py` to write each extracted image under `f"{statement_id}/images/{name}"`, and to call `app.core.audit.record_audit(session, user_id=None, action="ingestion.process", detail={"statement_id": statement_id, "prefix": prefix})` followed by an explicit `await session.commit()`, via `get_own_session()`, after all artifacts are successfully persisted — makes T016 pass (depends on T017)

**Checkpoint**: User Stories 1 AND 2 both work independently — full artifact set is durably persisted and every processing call is auditable with zero backend-table writes.

---

## Phase 5: User Story 3 - Fail explicitly when extraction cannot succeed (Priority: P3)

**Goal**: Every failure mode (unknown statement, unreadable source, unreachable/broken processing engine, empty content) produces an explicit, distinguishable outcome — never a silent or partial success.

**Independent Test**: Trigger each failure condition independently (bad `statement_id`, a `seaweed_file_id` pointing at a missing object, a `MineruClient` that raises) and confirm the documented status code/behavior from [contracts/ingestion-process.md](contracts/ingestion-process.md) in each case.

### Tests for User Story 3 ⚠️

- [X] T019 [P] [US3] In `tests/features/ingestion/test_service.py`: test that an unknown `statement_id` (well-formed UUID, no matching row) raises an `HTTPException` with status `404`, and that neither the storage client nor `get_mineru_client().parse_document` is ever invoked (spec SC-002)
- [X] T020 [P] [US3] In `tests/features/ingestion/test_service.py`: test that a `seaweed_file_id` with no `/`, or a storage `get_object` call that raises, results in an `HTTPException` with status `502` whose detail identifies a source-retrieval failure — and that the MinerU client is never called in this case
- [X] T021 [P] [US3] In `tests/features/ingestion/test_service.py`: test that the MinerU client's `parse_document` raising (simulating a network error or an unparsable ZIP) results in an `HTTPException` with status `502` whose detail identifies a processing-engine failure
- [X] T022 [P] [US3] In `tests/features/ingestion/test_service.py`: test that a MinerU result with empty/blank markdown and an empty content list still returns a successful `ProcessStatementResult` (artifacts are written, even if empty) rather than raising

### Implementation for User Story 3

- [X] T023 [US3] In `app/features/ingestion/service.py`, raise `HTTPException(404, "statement not found")` immediately when the `StatementFiles` lookup returns no row, before any storage or MinerU call — makes T019 pass
- [X] T024 [US3] In `app/features/ingestion/service.py`, validate that `seaweed_file_id` contains `/` before splitting, and wrap the `get_object` call in `try/except` → `HTTPException(502, "failed to retrieve source document: ...")` — makes T020 pass
- [X] T025 [US3] In `app/features/ingestion/service.py`, wrap the `get_mineru_client().parse_document(...)` call in `try/except` → `HTTPException(502, "document processing engine failed: ...")`, distinct from the source-retrieval message in T024 — makes T021 pass
- [X] T026 [US3] Confirm/adjust the artifact-assembly logic in `app/features/ingestion/service.py` so an empty markdown/content-list result from `parse_document()` is written and returned normally rather than treated as an error — makes T022 pass

**Checkpoint**: All three user stories are independently functional; every documented failure path in [contracts/ingestion-process.md](contracts/ingestion-process.md) is enforced and tested.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T027 [P] Run Ruff, `black --check`, and `mypy` across all new/changed files (`app/core/config.py`, `app/features/ingestion/**`, `app/main.py`, `tests/conftest.py`) and fix any violations
- [X] T028 [P] Run the offline unit-test steps of [quickstart.md](quickstart.md) end-to-end (`pytest tests/features/ingestion/ -v`, using the test doubles from US1–US3) and confirm all pass
- [X] T029 Run the real-engine steps of [quickstart.md](quickstart.md) against the live MinerU instance and object store the requester is pointing `MINERU_API_URL`/`MINERU_API_KEY` at; record any discrepancy between the assumed ZIP layout and the real one back into [research.md](research.md) §1

---

## Deferred (explicitly out of scope for this task list)

- **`MockMineruClient`**: a second `MineruClient` implementation returning fixed, deterministic
  artifacts in the same `ParsedDocument` shape as `HttpMineruClient`, wired into `get_mineru_client()`
  behind `settings.use_mock_mineru`. Confirmed with the requester: not needed now, since real-server
  validation (T029) is happening first. When picked up later, it should require no change to
  `service.py` or any consumer — only to `get_mineru_client()`'s construction branch (research.md §8).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; extends US1's `mineru_client.py`/`service.py` (T011–T013), so start after US1's implementation tasks land, not just after Foundational
- **User Story 3 (Phase 5)**: Depends on Foundational; adds error branches to the same `service.py` built in US1/US2, so implement after T013/T018 exist
- **Polish (Phase 6)**: Depends on all three user stories being complete

### User Story Dependencies

- **US1 (P1)**: No dependency on US2/US3; independently testable as soon as Foundational is done
- **US2 (P2)**: Extends the same `mineru_client.py`/`service.py` files US1 creates — sequenced after US1's implementation, not parallel with it, despite being a separate story
- **US3 (P3)**: Extends the same `service.py` — sequenced after US2 (or at least after US1) for the same reason

### Within Each User Story

- Tests are written first and must fail before the paired implementation task
- `mineru_client.py` changes precede the `service.py` changes that consume them
- `service.py` changes precede the `router.py` wiring that exposes them

### Parallel Opportunities

- T002, T003 (Setup) can run in parallel with T001
- T005 (Foundational) can run in parallel with T004; T006/T007 depend on T005
- Within US1: T008, T009, T010 (all different test files) can run in parallel
- Within US2: T015, T016 can run in parallel with each other (different files) but not with US1's implementation tasks (they extend the same files)
- Within US3: T019–T022 (all in the same file, `test_service.py`) are logically independent test cases but touch one shared file — treat as parallel-safe only if using separate test functions with no shared fixtures being edited concurrently; otherwise implement sequentially
- T027, T028 (Polish) can run in parallel; T029 is sequential (a live, manual validation run)

---

## Parallel Example: User Story 1

```bash
# Launch all three test-writing tasks for User Story 1 together:
Task: "Write test_mineru_client.py ZIP-extraction helper tests"
Task: "Write test_service.py happy-path test with mocked session/storage/MineruClient test double"
Task: "Write test_router.py auth + happy-path test"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: run `pytest tests/features/ingestion/` — happy-path extraction + minimal persistence works independently
5. This is a legitimate MVP: a caller already gets extracted markdown + content-list content at a known location; images and audit compliance land next

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add US1 → validate independently → MVP
3. Add US2 → validate independently → full artifact set + compliance guarantees
4. Add US3 → validate independently → hardened failure behavior
5. Polish → lint/type-check clean, full quickstart validated against a real MinerU instance

---

## Notes

- [P] tasks touch different files with no unmet dependency
- [Story] labels map every story-phase task to spec.md's US1/US2/US3 for traceability
- US2 and US3 are not fully independent of US1 at the *file* level (they extend `mineru_client.py`/`service.py` rather than adding new files) — they remain independent at the *behavioral/test* level, per their own Independent Test criteria
- Commit after each task or logical group
- Avoid: vague tasks, unnecessary same-file conflicts, skipping a story's tests before its implementation
