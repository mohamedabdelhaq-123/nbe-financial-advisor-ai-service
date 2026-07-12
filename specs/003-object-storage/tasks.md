---

description: "Task list for Object Storage Infrastructure"
---

# Tasks: Object Storage Infrastructure

**Input**: Design documents from `/specs/003-object-storage/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/storage-module-interface.md](./contracts/storage-module-interface.md), [quickstart.md](./quickstart.md)

**Tests**: Included — Constitution Principle I ("Every feature MUST ship with automated unit and integration tests") makes these mandatory, not optional, for this project.

**Organization**: Tasks are grouped by user story (from spec.md: US1/P1, US2/P2, US3/P3) to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single existing project (feature-sliced FastAPI service, Constitution
Principle V) — this feature only touches `app/core/`, `tests/`,
`.env.example`, and `pyproject.toml`. No new top-level directories.

---

## Phase 1: Setup

**Purpose**: Add the one new runtime dependency this feature needs

- [X] T001 Add `aioboto3` as a runtime dependency via `uv add aioboto3` (updates `pyproject.toml` and `uv.lock`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config plumbing and shared test fixtures every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 [P] Add `storage_s3_bucket`, `storage_s3_endpoint_url`, `storage_s3_region`, `storage_s3_access_key`, `storage_s3_secret_key`, `storage_s3_use_path_style` fields to the `Settings` class in `app/core/config.py` (per data-model.md's Configuration Entity table) — **no fail-fast check yet**, that's added in US3 (Phase 5)
- [X] T003 [P] Add commented example `STORAGE_S3_*` values to `.env.example`, matching the field names from T002 (per plan.md §"Config surface")
- [X] T004 [P] Add a `real_s3_storage_env` fixture to `tests/conftest.py` that reads `STORAGE_S3_ENDPOINT_URL`/`STORAGE_S3_BUCKET`/`STORAGE_S3_ACCESS_KEY`/`STORAGE_S3_SECRET_KEY` from the environment and calls `pytest.skip(...)` if any are unset (mirrors the existing `backend_db_host`-empty-skips pattern; see research.md §7)

**Checkpoint**: Config surface and shared test fixture exist — user story implementation can now begin

---

## Phase 3: User Story 1 - Persist and retrieve a blob from any feature (Priority: P1) 🎯 MVP

**Goal**: Give any part of the codebase (routers, background jobs, agent/graph nodes) a way to write, read, check existence of, delete, and list blobs against the configured S3-compatible store.

**Independent Test**: From application code, write a blob under a logical key and read the same blob back byte-for-byte, using a running instance pointed at a real configured object store (per quickstart.md Scenario 3).

### Tests for User Story 1 ⚠️

> Write these tests FIRST, and confirm T005 fails (import error) and T006 skips/fails before T007 is implemented.

- [X] T005 [P] [US1] Write `test_rejects_path_traversal` in `tests/core/test_storage.py`, asserting `validate_storage_key` raises `ValueError` for an absolute-path key and for a key containing a `..` traversal segment (per contracts/storage-module-interface.md, FR-007/SC-004)
- [X] T006 [US1] Write `tests/integration/test_storage_s3.py` using the `real_s3_storage_env` fixture (T004): perform a real `put_object` → `head_object`/`get_object` → `list_objects_v2` → `delete_object` → `head_object` round-trip against the configured bucket, asserting the read-back bytes match exactly, existence flips correctly across the delete, and the list call returns exactly the expected key(s) (covers spec.md US1 Acceptance Scenarios 1–4)

### Implementation for User Story 1

- [X] T007 [US1] Implement `app/core/storage.py`: a module-level `_session = aioboto3.Session()` singleton, `get_storage_backend()` (returns a fresh unentered `_session.client("s3", ...)` configured from `settings.storage_s3_*`, per contracts/storage-module-interface.md), and `validate_storage_key(key)` (rejects absolute paths and `..` traversal via `posixpath.normpath`, per data-model.md's validation rule) — makes T005 pass and enables T006 to exercise real behavior

**Checkpoint**: User Story 1 is fully functional and independently testable — blobs can be written, read, checked, deleted, and listed against a configured S3-compatible store.

---

## Phase 4: User Story 2 - Point the service at the operating environment's object store via configuration (Priority: P2)

**Goal**: Confirm the same code retargets to a different S3-compatible endpoint/bucket purely through configuration, with zero source changes — this story adds no new production code beyond Phase 2 + Phase 3, since `get_storage_backend()` already reads `settings` fresh on every call.

**Independent Test**: Re-run the Phase 3 round-trip test against a second S3-compatible endpoint/bucket, changing only environment configuration (per quickstart.md Scenario 4).

### Implementation for User Story 2

- [X] T008 [US2] Re-run `tests/integration/test_storage_s3.py` with `STORAGE_S3_ENDPOINT_URL`/`STORAGE_S3_BUCKET`/`STORAGE_S3_ACCESS_KEY`/`STORAGE_S3_SECRET_KEY` pointed at a second, distinct S3-compatible endpoint/bucket; confirm it passes unchanged, and record the result in a short note appended to `specs/003-object-storage/quickstart.md` under Scenario 4 (covers spec.md US2 Acceptance Scenarios 1–2 / SC-002)

**Checkpoint**: User Stories 1 and 2 both work independently — the config surface is proven retargetable.

---

## Phase 5: User Story 3 - Fail fast on incomplete storage configuration (Priority: P3)

**Goal**: The service refuses to start if `storage_s3_bucket`/`storage_s3_access_key`/`storage_s3_secret_key` are incomplete, with an explicit error naming what's missing — instead of deferring the failure to first storage use.

**Independent Test**: Start the service with incomplete storage credentials and confirm immediate startup failure with a clear error (per quickstart.md Scenario 1).

### Tests for User Story 3 ⚠️

> Write this test FIRST, and confirm it fails before T010 is implemented.

- [X] T009 [P] [US3] Add a test to `tests/core/test_config.py` asserting that importing `app.core.config` with `STORAGE_S3_BUCKET`/`STORAGE_S3_ACCESS_KEY`/`STORAGE_S3_SECRET_KEY` incomplete raises `RuntimeError`, following the same pattern already used there for the existing `openai_api_key`/`ai_service_token` fail-fast checks

### Implementation for User Story 3

- [X] T010 [US3] Add a fail-fast check in `app/core/config.py` immediately after `settings = Settings()`: raise `RuntimeError` naming the missing field(s) if `storage_s3_bucket`, `storage_s3_access_key`, or `storage_s3_secret_key` is empty (per data-model.md's Configuration Entity validation rule; mirrors the existing `openai_api_key`/`ai_service_token` checks) — makes T009 pass

**Checkpoint**: All three user stories are independently functional — misconfiguration is now caught at startup, not at first use.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all stories

- [X] T011 [P] Run the full quickstart.md validation (`specs/003-object-storage/quickstart.md`, all 4 scenarios) end-to-end
- [X] T012 [P] Run `uv run mypy app/core/storage.py` and `uv run ruff check`; fix any findings
- [X] T013 Run the full suite (`uv run pytest`) to confirm no regressions in existing tests

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001) completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2) completion
- **User Story 2 (Phase 4)**: Depends on User Story 1 (Phase 3) completion — its test re-runs US1's test file, so it needs T007 to exist. Not independent of US1 the way US1 is independent of everything else (this is expected: US2 validates a property of the US1 implementation rather than adding new code).
- **User Story 3 (Phase 5)**: Depends on Foundational (Phase 2) only — independent of US1/US2, could be implemented in parallel with them by a different developer
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests written and failing before implementation (T005/T006 before T007; T009 before T010)
- Checkpoint at the end of each phase before moving to the next priority

### Parallel Opportunities

- T002, T003, T004 (Foundational) can all run in parallel — different files, no interdependency
- T005 (US1 unit test) can run in parallel with T004/T009 — different files
- T009 (US3 test) can start as soon as Foundational is done, in parallel with all of US1/US2 — different files, no shared dependency beyond T002
- T011, T012 (Polish) can run in parallel with each other; T013 should run last as the final regression gate

---

## Parallel Example: Foundational + User Story 1 kickoff

```bash
# Once T001 is done, launch all of Foundational together:
Task: "Add storage_s3_* Settings fields to app/core/config.py"
Task: "Add STORAGE_S3_* example vars to .env.example"
Task: "Add real_s3_storage_env fixture to tests/conftest.py"

# Once Foundational is done, US1's test can start immediately alongside US3's test:
Task: "Write test_rejects_path_traversal in tests/core/test_storage.py"
Task: "Add fail-fast RuntimeError test to tests/core/test_config.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002–T004)
3. Complete Phase 3: User Story 1 (T005–T007)
4. **STOP and VALIDATE**: run quickstart.md Scenarios 2 and 3 independently
5. This is a usable MVP — other features can already depend on `get_storage_backend()`

### Incremental Delivery

1. Setup + Foundational → config surface and fixture ready
2. User Story 1 → validate independently → mergeable (core capability exists)
3. User Story 2 → validate retargeting → mergeable (no new code, just proof)
4. User Story 3 → validate fail-fast → mergeable (safety net added)
5. Polish → full regression + lint/type gate

### Parallel Team Strategy

With two developers: one takes US1 → US2 (sequential, since US2 depends on
US1's test file existing); the other can start US3 as soon as Foundational
is done, entirely in parallel, since US3 only touches `config.py` and
`test_config.py`.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Verify tests fail before implementing (T005/T006 before T007; T009 before T010)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
