---

description: "Task list for feature implementation"
---

# Tasks: Mock MinerU Client for Offline Ingestion

**Input**: Design documents from `/specs/011-mineru-mock-client/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle I mandates automated tests for every feature, and the feature description explicitly requested factory-selection tests mirroring `tests/features/ingestion/test_normalizer.py:357-372`.

**Organization**: Tasks are grouped by user story (P1/P2/P3 from spec.md) to enable independent testing of each story. This feature is small and touches only two files
(`app/features/ingestion/mineru_client.py` and `tests/features/ingestion/test_mineru_client.py`, plus one test added to `tests/features/ingestion/test_service.py`), so most tasks are sequential (same-file edits) rather than parallel — that is expected, not an oversight.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every task description

## Path Conventions

Single FastAPI project, feature-bounded vertical slices (constitution Principle V). All paths below are repository-root-relative, entirely within the existing `app/features/ingestion/` slice and its `tests/features/ingestion/` counterpart.

---

## Phase 1: Setup

Not applicable. No new project initialization, dependency, or tooling change is required — this feature reuses the existing Python/FastAPI/pytest stack, the existing `settings.use_mock_mineru` configuration flag (already declared and validated in `app/core/config.py`), and the existing `MineruClient` Protocol / `ParsedDocument` dataclass as-is.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement `MockMineruClient` and wire it into the factory. This is the actual defect fix and is a blocking prerequisite for all three user stories — none of them can be exercised or tested until both tasks below are done.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T001 Add a `MockMineruClient` class to `app/features/ingestion/mineru_client.py`, placed after `HttpMineruClient` and before `get_mineru_client()`. It must implement the `MineruClient` Protocol (`async def parse_document(self, file_bytes: bytes, filename: str) -> ParsedDocument`) with a one-line class docstring in the style of `app/features/ingestion/normalizer/mock.py` (e.g. `"""Deterministic mock \`MineruClient\` — no network call."""`). It MUST NOT branch on `settings.use_mock_mineru` or otherwise inspect `file_bytes`/`filename` — it always returns the same fixed `ParsedDocument`, per data-model.md:
  - `markdown`: non-empty, statement-shaped text (e.g. a heading plus a one-row Markdown table) describing one fixed mock transaction (date, merchant-like text, amount).
  - `content_list`: exactly two entries describing that same transaction — `{"type": "text", "text": <statement-like text>, "page_idx": 0}` and `{"type": "table", "table_body": "<table>...</table>"}` (a single-row HTML table string; the key MUST be `table_body`, not `rows`, because `app/features/ingestion/normalizer/chunking.py::_split_table_entry` reads exactly that key).
  - `images`: always `{}`.
- [X] T002 Update `get_mineru_client()` in `app/features/ingestion/mineru_client.py` to branch: return `MockMineruClient()` when `settings.use_mock_mineru` is `True`, else `HttpMineruClient()` — mirroring `get_normalizer_client()` in `app/features/ingestion/normalizer/__init__.py:47-49` exactly. In the same task, update the module's top-of-file docstring, which currently says the mock is "deferred — not built in this feature" and that `get_mineru_client()` "Always returns `HttpMineruClient` today" — both statements are now false. Reword to describe `HttpMineruClient` and `MockMineruClient` as the two swappable implementations behind the `MineruClient` protocol. Depends on T001 (same file, sequential).

**Checkpoint**: `MockMineruClient` exists with its fixed deterministic output and is wired into `get_mineru_client()` via `settings.use_mock_mineru`. No automated tests yet — Phases 3–5 add those, organized by which acceptance criteria they verify.

---

## Phase 3: User Story 1 - Run ingestion fully offline with no reachable document-parsing service (Priority: P1) 🎯 MVP

**Goal**: Prove that with the offline-mode setting enabled and no document-parsing service reachable, the full statement-ingestion flow completes successfully via the real `get_mineru_client()` factory wiring — not a test-only override.

**Independent Test**: Enable `settings.use_mock_mineru`, do not monkeypatch `get_mineru_client` itself, run `process_statement(...)`, and verify it completes and persists parsed output.

### Tests for User Story 1

- [X] T003 [US1] Add `test_offline_mode_setting_alone_routes_through_mock_mineru` (async, `@pytest.mark.asyncio`) to `tests/features/ingestion/test_service.py`. Reuse the existing `_FakeStatement`/`_session_gen_for`/`_own_session_gen`/`_FakeS3`/`_patch_storage` fixtures already in that file. Unlike every other test in the file, do **not** call `_patch_mineru(...)` — instead `import app.features.ingestion.mineru_client as mineru_client_module` and `monkeypatch.setattr(mineru_client_module.settings, "use_mock_mineru", True)`, so the real (unpatched) `get_mineru_client()` factory runs. Call `process_statement(session_gen=..., own_session_gen=..., statement_id=STATEMENT_ID)` and assert: it returns successfully (no exception, no attempted real HTTP call — `HttpMineruClient` would fail fast on the empty/unset `mineru_api_url` in the test environment if the factory picked the wrong branch); and the persisted `markdown.md` / `content_list.json` bodies in `s3.put_calls` match `MockMineruClient`'s fixed output from T001 (non-empty markdown; content_list with the `text` and `table` entries). This is the closing proof that `USE_MOCK_MINERU=1` actually takes effect end-to-end (the defect this whole feature fixes), not just that a class exists.

**Checkpoint**: User Story 1 is independently verified — offline ingestion completes end-to-end with zero MinerU connectivity, through the real configuration flag, not a test double.

---

## Phase 4: User Story 2 - Verify offline/real selection is correct and consistent (Priority: P2)

**Goal**: Prove `get_mineru_client()` reliably selects the offline implementation when enabled and the real one when disabled.

**Independent Test**: Toggle `settings.use_mock_mineru` on and off and assert which implementation type is returned, independent of running any ingestion flow.

### Tests for User Story 2

- [X] T004 [US2] Add `test_get_mineru_client_returns_mock_when_use_mock_mineru(monkeypatch)` to `tests/features/ingestion/test_mineru_client.py`. Import `get_mineru_client`, `MockMineruClient`, `HttpMineruClient` from `app.features.ingestion.mineru_client`, plus the module itself as `mineru_client_module`. Patch on the module's own `settings` reference — `monkeypatch.setattr(mineru_client_module.settings, "use_mock_mineru", True)` — not `app.core.config.settings` directly (mirror the exact rationale documented at `tests/features/ingestion/test_normalizer.py:357-361`: a reload elsewhere in the suite rebinds that reference). Assert `isinstance(get_mineru_client(), MockMineruClient)`.
- [X] T005 [US2] Add `test_get_mineru_client_returns_http_when_not_mock(monkeypatch)` to the same file, same import pattern, `monkeypatch.setattr(mineru_client_module.settings, "use_mock_mineru", False)`, asserting `isinstance(get_mineru_client(), HttpMineruClient)`. Depends on T004 (same file, sequential).

**Checkpoint**: User Story 2 is independently verified — the selection logic is deterministic and test-covered in both directions.

---

## Phase 5: User Story 3 - Offline parsing output is plausible enough for downstream processing (Priority: P3)

**Goal**: Prove the mock's fixed output is non-empty, deterministic, and genuinely consumable by the real (non-mocked) downstream chunking logic — not just "non-empty" by inspection.

**Independent Test**: Call `MockMineruClient().parse_document(...)` directly and inspect its output; separately, feed that output through the real chunking function and confirm it doesn't error.

### Tests for User Story 3

- [X] T006 [US3] Add `test_mock_mineru_client_returns_fixed_deterministic_content` (async) to `tests/features/ingestion/test_mineru_client.py`. Call `await MockMineruClient().parse_document(b"one-file", "a.pdf")` and `await MockMineruClient().parse_document(b"a-completely-different-file", "b.pdf")`. Assert both results are equal (determinism regardless of input, FR-004); `markdown` is non-empty; `content_list` has exactly two entries, one with `"type": "text"` and one with `"type": "table"` and a non-empty `"table_body"` string key (not `"rows"`); and `images == {}`.
- [X] T007 [US3] Add `test_mock_mineru_client_table_body_is_parseable_by_real_chunking` (async) to `tests/features/ingestion/test_mineru_client.py`. Import `_split_into_chunks` from `app.features.ingestion.normalizer.chunking`. Call `MockMineruClient().parse_document(...)`, then pass the resulting `content_list` and `markdown` into `_split_into_chunks(content_list, markdown)`. Assert it returns at least one non-empty chunk without raising — this directly proves User Story 3's "plausible enough for downstream processing" claim against the real (non-mocked) chunking code path, not just a schema check. Depends on T006 (same file, sequential).

**Checkpoint**: All three user stories are independently verified. The feature is complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T008 Run the full regression + gate suite per quickstart.md steps 4–5: `uv run pytest tests/features/ingestion/ -v` (confirm all pre-existing tests, including `HttpMineruClient`/ZIP-extraction tests and `_FakeMineruClient`-injected tests in `test_service.py`, still pass unmodified), then `uv run pytest && uv run ruff check . && uv run black --check . && uv run mypy .` for the full CI gate. Depends on T001–T007.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: N/A — nothing to do.
- **Foundational (Phase 2)**: No dependencies — BLOCKS all user stories. T002 depends on T001 (same file).
- **User Stories (Phase 3–5)**: All depend on Foundational (Phase 2) completion. T003 (US1), T004–T005 (US2), and T006–T007 (US3) are independent *of each other* in the sense that any one story's tests can be written and run without the others existing — but T004/T005 share a file (sequential) and T006/T007 share a file (sequential).
- **Polish (Phase 6)**: Depends on all of Phases 2–5 being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2). No dependency on US2 or US3.
- **User Story 2 (P2)**: Can start after Foundational (Phase 2). No dependency on US1 or US3.
- **User Story 3 (P3)**: Can start after Foundational (Phase 2). No dependency on US1 or US2.

### Parallel Opportunities

Limited, because this feature touches only two files. The only genuine cross-file parallel opportunity is:

- Once Phase 2 (Foundational) is complete, **T003 (US1, in `test_service.py`)** can run in parallel with **T004 (US2, in `test_mineru_client.py`)** and **T006 (US3, in `test_mineru_client.py`)** — different files/stories, no shared state. (T004→T005 and T006→T007 remain sequential within `test_mineru_client.py`.)

No task in this feature is parallel with another task in the *same* file — Foundational (T001→T002), and each story's own multi-task file (T004→T005, T006→T007) are all sequential edits to a shared file.

---

## Parallel Example: Across User Stories (after Phase 2 completes)

```bash
# These three can be started together — different files, independent stories:
Task: "T003 [US1] Add offline end-to-end test in tests/features/ingestion/test_service.py"
Task: "T004 [US2] Add factory-selection test in tests/features/ingestion/test_mineru_client.py"
Task: "T006 [US3] Add fixed-content test in tests/features/ingestion/test_mineru_client.py"
```

Note: T004 and T006 land in the same file — if truly run by separate agents in parallel, reconcile the merge before T005/T007 continue.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2: Foundational (T001–T002) — this is the actual bug fix.
2. Complete Phase 3: User Story 1 (T003) — proves the fix works end-to-end.
3. **STOP and VALIDATE**: `USE_MOCK_MINERU=1` now genuinely enables offline ingestion. This alone closes the defect described in plan.md's Summary.

### Incremental Delivery

1. Foundational (T001–T002) → the fix exists.
2. Add User Story 1 (T003) → proven end-to-end → MVP.
3. Add User Story 2 (T004–T005) → selection behavior is regression-proof.
4. Add User Story 3 (T006–T007) → output quality/downstream-plausibility is regression-proof.
5. Polish (T008) → full suite + lint/format/type gate green.

---

## Notes

- [P] tasks = different files, no dependencies — genuinely rare in this feature given its small footprint.
- [Story] label maps each task to its user story for traceability back to spec.md.
- Verify new tests fail (or would fail) before T001–T002 exist, then pass after — T003, T004–T005, and T006–T007 all depend on Foundational being done first.
- Commit after each phase (Foundational; then each user story) rather than each individual task, given how tightly the tasks within a phase share files.
- Avoid: adding failure-simulation or content-inspection logic to `MockMineruClient` (explicitly excluded by spec.md Clarifications, FR-008) and adding a `rows`-style table entry instead of `table_body` (would silently fail User Story 3).
