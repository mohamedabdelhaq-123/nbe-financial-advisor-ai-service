# Tasks: Normalizer Pipeline Rework

**Input**: Design documents from `/specs/016-normalizer-pipeline-rework/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Included as first-class tasks, not optional — Constitution Principle I mandates automated
unit/integration tests for every feature unconditionally, overriding this template's generic
"tests are optional" default. All LLM-facing tests stay mock-first per Principle I; nothing here
makes a real model or Langfuse call.

**Organization**: Tasks are grouped by user story (spec.md priorities P1/P1/P2/P2/P3/P2) to enable
independent implementation and testing of each story. **Note on FR-004** (content presentation):
spec.md's requirements include FR-004 but no dedicated user story owns it — it has no independent
acceptance scenario distinct from "extraction generally works better." It's treated as shared,
cross-cutting infrastructure and lives in the Foundational phase (T010-T012), not its own story phase.
**Note on FR-003** (`balance`/`merchant_normalized`): same situation as FR-004 — no dedicated user
story owns it in spec.md. Unlike FR-004, it's a self-contained, independently-testable capability
thematically part of User Story 1 ("output matches the backend's real data model"), so its tasks are
folded into US1's phase (T015-T016, T018-T020) rather than Foundational. *(Both notes added during
`/speckit-analyze` remediation — FR-003 had zero task coverage in the original version of this file.)*

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1-US6, matching spec.md)
- File paths are exact; all paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Confirm the ground this feature builds on before restructuring anything

- [X] T001 Create `app/features/ingestion/normalizer/agents/__init__.py` and `app/features/ingestion/normalizer/agents/chunked_langgraph/__init__.py` (empty package skeleton)
- [X] T002 [P] Confirm no new third-party dependency is required: verify `langgraph`'s installed version exposes `langgraph.types.Send`, `langgraph.types.RetryPolicy`, and honors `config={"max_concurrency": ...}` in `pregel/_executor.py` (research.md §6) — no `pyproject.toml`/`uv.lock` change expected

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Package restructuring, interface/config surface, and content-rendering infrastructure
every user story either depends on or is easiest to build against once in place.

**⚠️ CRITICAL**: No user story task should start until this phase is complete.

- [X] T003 Move `app/features/ingestion/normalizer/graph.py` → `app/features/ingestion/normalizer/agents/chunked_langgraph/graph.py` (`git mv`, no content changes yet)
- [X] T004 [P] Move `app/features/ingestion/normalizer/prompts.py` and `app/features/ingestion/normalizer/prompt_templates/normalization.jinja2` → `app/features/ingestion/normalizer/agents/chunked_langgraph/` (`git mv`, no content changes yet)
- [X] T005 [P] Move `app/features/ingestion/normalizer/chunking.py` → `app/features/ingestion/normalizer/agents/chunked_langgraph/chunking.py` (`git mv`, no content changes yet)
- [X] T006 Update every import referencing the moved modules — `app/features/ingestion/normalizer/__init__.py`, `tests/features/ingestion/test_normalizer.py` — to their new `agents/chunked_langgraph/` paths
- [X] T007 Rename `LangGraphNormalizerClient` → `ChunkedLangGraphNormalizerClient` in `app/features/ingestion/normalizer/agents/chunked_langgraph/graph.py` and every import/export site (`app/features/ingestion/normalizer/__init__.py`, tests)
- [X] T008 Add `normalizer_strategy: Literal["chunked_langgraph"] = "chunked_langgraph"` and `normalization_est_tokens_per_row: int = Field(default=450, gt=0)` to `ChatModelSettings` in `app/core/config.py` (data-model.md "New configuration")
- [X] T009 Update `get_normalizer_client()` in `app/features/ingestion/normalizer/__init__.py` to dispatch on `settings.chat_model.normalizer_strategy` instead of only the mock/real bool branch (mock check stays first; the strategy dispatch governs which real implementation is constructed)
- [X] T010 [P] Create `app/features/ingestion/normalizer/agents/chunked_langgraph/markdown_render.py` implementing the per-`content_list`-entry-type renderer from research.md §4 (FR-004): `text`/header-family/`list`/`equation`/`image`/`table`/`chart`/`code`/unknown-fallback branches; table HTML kept verbatim
- [X] T011 [P] Unit tests for the markdown renderer — one case per entry type from research.md §4's table, plus the unknown-type fallback — in `tests/features/ingestion/test_markdown_render.py`
- [X] T012 Wire `markdown_render.py` into `agents/chunked_langgraph/chunking.py`'s `_build_prompt()`, replacing `json.dumps(chunk)` with the rendered text

**Checkpoint**: Package layout, config surface, and content rendering are in place. User story phases
below can now proceed in priority order (or in parallel, if staffed).

---

## Phase 3: User Story 1 - Normalized output matches the backend's real data model (Priority: P1) 🎯 MVP

**Goal**: `extra_fields` (statement-level and transaction-level) returned as a key-value map, never a
list of `{key, value}` pairs; each transaction also carries dedicated `balance` and
`merchant_normalized` fields (FR-003) rather than folding that data into the general facts map.

**Independent Test**: Normalize a statement with known extra facts (e.g. an opening balance, a
reference number) and confirm those facts arrive as a directly-addressable map, with no list wrapper
anywhere in the output, omitted entirely (not an empty object) when there are none; confirm a
transaction whose source states a running balance and a recognizable merchant returns both as
dedicated fields, `null` when not determinable.

### Tests for User Story 1

- [X] T013 [P] [US1] Unit test: `normalize_statement()` converts statement-level `extra_fields` from `list[{key,value}]` to `dict[str,str]`, omitted when empty, in `tests/features/ingestion/test_service.py`
- [X] T014 [P] [US1] Unit test: same list→dict conversion applied per-transaction, omitted when empty, in `tests/features/ingestion/test_service.py`
- [X] T015 [P] [US1] Unit test: `ExtractedTransaction.balance`/`merchant_normalized` accept and round-trip a value, default to `None` when absent, in `tests/features/ingestion/test_normalizer.py`
- [X] T016 [P] [US1] Unit test: `service/normalize.py` passes `balance`/`merchant_normalized` through into each transaction dict unconditionally (key always present, `null` when the source didn't determine one — not conditionally omitted like `extra_fields`), in `tests/features/ingestion/test_service.py`

### Implementation for User Story 1

- [X] T017 [US1] Implement the `extra_fields` list→dict conversion in `app/features/ingestion/service/normalize.py`, applied once at the response/storage boundary for both statement-level and transaction-level facts (research.md §1) (depends on T013, T014 existing and failing first)
- [X] T018 [US1] Add `balance: float | None` and `merchant_normalized: str | None` to `ExtractedTransaction` in `app/features/ingestion/normalizer/schemas.py` (data-model.md) (depends on T015 existing and failing first)
- [X] T019 [US1] Update `agents/chunked_langgraph/prompt_templates/normalization.jinja2` to instruct extraction of each transaction's running balance and a canonicalized merchant name, omitted/`null` rather than guessed when not stated (depends on T018)
- [X] T020 [US1] Implement the `balance`/`merchant_normalized` passthrough (always-present keys, `.get(...)` defaulting to `None`) in `service/normalize.py`'s transaction-building loop (depends on T016 existing and failing first, T018; same file as T017 — land sequentially, not concurrently, to avoid a same-file conflict)

**Checkpoint**: User Story 1 is independently functional and testable.

---

## Phase 4: User Story 2 - Real account number instead of a masked hint (Priority: P1)

**Goal**: Return the account number exactly as it appears in the source statement — never masked,
truncated, or redacted.

**Independent Test**: Normalize a statement whose source states a full account number and confirm the
returned value matches the source digits exactly; confirm it's `null` (not guessed) when no account
number is stated anywhere.

### Tests for User Story 2

- [X] T021 [P] [US2] Unit test: `ExtractedStatement.account_number` accepts and round-trips a raw digit string in `tests/features/ingestion/test_normalizer.py`
- [X] T022 [P] [US2] Unit test: `service/normalize.py` passes `account_number` through unmasked into `normalized_json`, `null` when absent, in `tests/features/ingestion/test_service.py`

### Implementation for User Story 2

- [X] T023 [US2] Rename `ExtractedStatement.account_hint` → `account_number: str | None` in `app/features/ingestion/normalizer/schemas.py`
- [X] T024 [US2] Update `agents/chunked_langgraph/prompt_templates/normalization.jinja2` to instruct exact, unmasked transcription of the account number; remove `account_hint` wording
- [X] T025 [US2] Update `account_hint` → `account_number` references in `agents/chunked_langgraph/graph.py`'s state/accumulation code and in `normalizer/mock.py`'s fixed mock result
- [X] T026 [US2] Rename `account_hint` → `account_number` in `app/features/ingestion/service/normalize.py`'s `normalized_json` assembly (depends on T023-T025; same file as US1's T017/T020 — land sequentially with US1, not concurrently)

**Checkpoint**: User Stories 1 and 2 are both independently functional and testable.

---

## Phase 5: User Story 3 - Faster processing through real concurrent extraction (Priority: P2)

**Goal**: Replace the hand-rolled batch-tick loop with LangGraph-native `Send` fan-out and
`max_concurrency`-bounded execution, without changing which transactions come out the other end.

**Independent Test**: Normalize the same large statement once with the concurrency limit raised and
once at its most conservative default; confirm both runs produce the same extracted transactions but
the higher-concurrency run completes faster.

### Tests for User Story 3

- [X] T027 [P] [US3] Unit test: the `Send`/reducer graph invoked with `max_concurrency=1` vs `max_concurrency=4` against a stubbed structured-output LLM produces an identical transaction set (FR-009), in `tests/features/ingestion/test_normalizer.py`
- [X] T028 [P] [US3] Unit test: one chunk's stub exhausting `with_retry`'s 3 attempts fails the entire `ainvoke()` call with no partial result returned, even when other chunks in the same run already succeeded (FR-016), in `tests/features/ingestion/test_normalizer.py`

### Implementation for User Story 3

- [X] T029 [US3] Rewrite `agents/chunked_langgraph/graph.py`: replace the `extract_batch` self-loop with a single-chunk `extract_chunk` node, a `Send`-dispatching conditional entry edge (one `Send` per chunk), `Annotated[list, operator.add]` reducers for `transactions`/`extra_fields`, and a first-non-null-wins reducer for `bank_name`/`account_number` (research.md §6) (depends on T027, T028 existing and failing first)
- [X] T030 [US3] Pass `config={"max_concurrency": settings.chat_model.normalization_max_parallel_chunks}` to `graph.ainvoke()` in `ChunkedLangGraphNormalizerClient.normalize()` (depends on T029)

**Checkpoint**: User Stories 1-3 are independently functional and testable.

---

## Phase 6: User Story 4 - Chunking sized by what actually risks a bad extraction (Priority: P2)

**Goal**: Portion boundaries driven primarily by estimated transaction-row count, not raw source
character length — and verified not to change *which* transactions come out, only how they're
batched (FR-009, SC-005).

**Independent Test**: Normalize a statement with wide variance in per-row text length and confirm
portion boundaries track row count, not text length; confirm a single unusually large row still hits
the fallback ceiling instead of breaking extraction; confirm the same statement yields the same
extracted transactions under the old character-based chunking and the new row-based chunking.

### Tests for User Story 4

- [X] T031 [P] [US4] Unit test: row-count-based portioning packs a stable number of `<tr>` rows per chunk regardless of per-row text-length variance, in `tests/features/ingestion/test_normalizer.py`
- [X] T032 [P] [US4] Unit test: the row cap equals `max(1, floor(0.7 * normalization_chunk_max_tokens / normalization_est_tokens_per_row))` per research.md §5, in `tests/features/ingestion/test_normalizer.py`
- [X] T033 [P] [US4] Unit test: a single row exceeding the fallback character ceiling on its own still produces a (oversized but non-empty) chunk rather than being dropped (FR-008), in `tests/features/ingestion/test_normalizer.py`
- [X] T034 [P] [US4] Unit test: non-`table` entries pack under the liberal fallback character ceiling, uncounted against the row cap, in `tests/features/ingestion/test_normalizer.py`
- [X] T035 [P] [US4] Unit test (SC-005/FR-009 regression guard): given a fixed multi-page fixture with a stubbed deterministic LLM, the set of extracted transactions is identical whether content is portioned by the old character-based chunking or the new row-based chunking — in `tests/features/ingestion/test_normalizer.py`. *(Added during `/speckit-analyze` remediation — SC-005 previously had zero task coverage.)*

### Implementation for User Story 4

- [X] T036 [US4] Rewrite `_split_into_chunks`/`_split_table_entry` in `agents/chunked_langgraph/chunking.py` for row-count-primary sizing of `table` entries, liberal packing of non-`table` entries, and a renamed `_MAX_PORTION_CHARS` fallback ceiling (depends on T031-T035 existing and failing first)

**Checkpoint**: User Stories 1-4 are independently functional and testable.

---

## Phase 7: User Story 5 - Room for more than one extraction strategy over time (Priority: P3)

**Goal**: Verify and document the strategy-swap seam already introduced in Foundational (T008, T009).

**Independent Test**: Confirm the normalization endpoint's request/response contract is identical
regardless of which value `normalizer_strategy` holds, and that the swap is a config change, not a
call-site change.

### Tests for User Story 5

- [X] T037 [P] [US5] Unit test: `get_normalizer_client()` returns `ChunkedLangGraphNormalizerClient` for `normalizer_strategy="chunked_langgraph"`, and an invalid value is rejected at config-parse time (`Literal`-enforced, Constitution VII fail-fast) rather than at call time, in `tests/features/ingestion/test_normalizer.py`

### Implementation for User Story 5

- [X] T038 [US5] Document the extension pattern (add a sibling `agents/<name>/` subpackage implementing `NormalizerClient`, add its `Literal` member, add one factory branch) as a module docstring in `app/features/ingestion/normalizer/__init__.py`

**Checkpoint**: User Stories 1-5 are independently functional and testable. Note: most of this story's
substance shipped in Foundational (T008, T009) — this phase is verification and documentation of that
seam, not new production behavior, which is expected given its P3/lowest priority.

---

## Phase 8: User Story 6 - Full observability into per-statement extraction cost and behavior (Priority: P2)

**Goal**: Every per-chunk LLM call carries business-context metadata (statement, chunk, prompt
version); tracing failures never affect extraction success.

**Independent Test**: Normalize a statement large enough to produce several concurrently-processed
chunks and confirm every resulting LLM call is grouped under one traceable unit for that statement,
each individually identifiable by which chunk it came from.

### Tests for User Story 6

- [X] T039 [P] [US6] Unit test: `NormalizerClient.normalize()` accepts required `statement_id`/`ocr_result_id` keyword args; `MockNormalizerClient.normalize()` accepts and ignores them, in `tests/features/ingestion/test_normalizer.py`
- [X] T040 [P] [US6] Unit test: the extraction call site passes `config={"metadata": {...}, "tags": [...]}` containing `statement_id`, `ocr_result_id`, `chunk_index`, `prompt_version` — asserted via a stub `Runnable` capturing the config it receives, no real model or Langfuse call, in `tests/features/ingestion/test_normalizer.py`
- [X] T041 [P] [US6] Unit test: `prompt_version` is a deterministic hash of the Jinja2 template source, stable across repeated calls, and changes when the template content changes, in `tests/features/ingestion/test_normalizer.py`

### Implementation for User Story 6

- [X] T042 [US6] Add required keyword-only `statement_id: str, ocr_result_id: str` params to `NormalizerClient.normalize()` in `app/features/ingestion/normalizer/schemas.py`; update `MockNormalizerClient.normalize()` in `normalizer/mock.py` to accept and ignore them (depends on T039 existing and failing first)
- [X] T043 [US6] Thread `statement_id`/`ocr_result_id` (already in scope) from `app/features/ingestion/service/normalize.py`'s call site into `get_normalizer_client().normalize(...)` (depends on T042)
- [X] T044 [US6] Compute `prompt_version` (short content hash of the rendered template source, e.g. `hashlib.sha256(...).hexdigest()[:8]`) once at load time in `agents/chunked_langgraph/prompts.py` (depends on T041 existing and failing first)
- [X] T045 [US6] Attach `config={"metadata": {"statement_id", "ocr_result_id", "chunk_index", "prompt_version"}, "tags": [f"ingestion.normalize.chunk:{chunk_index}"]}` to the structured-output `.ainvoke()` call inside `extract_chunk` in `agents/chunked_langgraph/graph.py` (depends on T040 existing and failing first, T042-T044)
- [X] T046 [US6] Add a `TODO` comment at T045's call site referencing this plan's tracked Constitution Principle III exception — the new `account_number` will reach telemetry unredacted via this same metadata path; not fixed here (plan.md Constitution Check, research.md §10)
- [ ] T047 [US6] Manual verification (not automatable — requires a real Langfuse instance): run quickstart.md's "Observability validation" section against the reference statement with concurrency raised above 1; confirm concurrent chunks group under one trace (FR-015) and are individually filterable by the new metadata

**Checkpoint**: All six user stories are independently functional and testable.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Repo hygiene, cross-repository coordination tracking, and final end-to-end validation.

- [X] T048 [P] Document `AI_SERVICE_NORMALIZER_STRATEGY` / `AI_SERVICE_NORMALIZATION_EST_TOKENS_PER_ROW` in `.env.example`
- [X] T049 [P] Add a one-line supersession pointer to `specs/005-statement-normalization/contracts/ingestion-normalize.md` linking to this feature's revised `contracts/ingestion-normalize.md`
- [ ] T050 Open/link a backend-side tracking issue for FR-011's coordinated rollout of the breaking output-shape change, and reference it in this feature's PR description (plan.md, research.md §9 — cross-repository process dependency, not code)
- [ ] T051 Open/link a separate backlog item for the telemetry-redaction gap flagged at T046, and reference it in this feature's PR description (plan.md Constitution Check, research.md §10)
- [ ] T052 Run quickstart.md's full validation suite end-to-end (output-shape, SC-003 concurrency speedup, SC-004 chunking quality, SC-005 chunking-equivalence, FR-016 all-or-nothing failure, observability) against a real statement and a real LLM before merge

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS every user story (package paths, settings,
  and the factory dispatch every story's tasks reference or build alongside).
- **User Stories (Phase 3-8)**: All depend on Foundational completion. Priority order is
  US1 → US2 → US3 → US4 → US5 → US6, but stories are largely file-independent enough to reorder or
  parallelize across developers once Foundational is done (see below).
- **Polish (Phase 9)**: Depends on all six user stories being complete.

### User Story Dependencies

- **US1 (P1)**: No dependency on any other story — touches `service/normalize.py`,
  `normalizer/schemas.py`, and the prompt template (T018/T019 for `balance`/`merchant_normalized`
  widened its footprint beyond `service/normalize.py` alone during `/speckit-analyze` remediation).
- **US2 (P1)**: No dependency on US1 — touches the same three files as US1
  (`normalizer/schemas.py`, the prompt template, `service/normalize.py`) plus `mock.py`. Land US1 and
  US2 sequentially within one owner (or rebase carefully) to avoid same-file conflicts on
  `schemas.py`/the prompt template/`normalize.py` — each edits a different field, but all three files
  are shared between the two stories.
- **US3 (P2)**: No dependency on US1/US2 — touches only `agents/chunked_langgraph/graph.py`. If US2
  lands first, US3's rewrite naturally inherits the renamed `account_number` field; if US3 lands
  first, US2's T025 applies its rename against the already-rewritten `graph.py` instead — both orders
  work.
- **US4 (P2)**: No dependency on US1/US2/US3 — touches only `agents/chunked_langgraph/chunking.py`.
- **US5 (P3)**: Depends on Foundational only (T008, T009 already deliver its substance); its own phase
  is verification/documentation.
- **US6 (P2)**: Touches `normalizer/schemas.py`, `mock.py`, `service/normalize.py`, `graph.py`, and
  `prompts.py` — the widest-reaching story. Should land **last** among the stories in practice (even
  though nothing technically blocks it earlier) since it's the only story whose call-site changes
  (T042, T043) touch every other story's files; landing it last avoids repeated rebasing.

### Within Each User Story

- Tests are written first and MUST fail before their corresponding implementation task.
- Schema/interface changes before the graph/service code that consumes them.
- Story complete (all its tasks done, its Independent Test passes) before treating it as shippable.

### Parallel Opportunities

- T004 and T005 (independent file moves) can run in parallel with each other and with T003.
- T010 and T011 (renderer + its tests) can run in parallel with T003-T009 (they touch a new file with
  no dependency on the moves/renames).
- All tasks marked `[P]` within a single story's Tests subsection can run in parallel (different test
  functions, potentially different files).
- Once Foundational (Phase 2) is done, US1/US2/US3/US4 can be staffed to different developers in
  parallel (see per-story file-overlap notes above, particularly the US1/US2 shared-file caveat);
  US5 and US6 are best done last.

---

## Parallel Example: User Story 1

```bash
# Launch all four User Story 1 tests together (different test functions, safe to author in parallel):
Task: "Unit test: statement-level extra_fields list→dict conversion in tests/features/ingestion/test_service.py"
Task: "Unit test: transaction-level extra_fields list→dict conversion in tests/features/ingestion/test_service.py"
Task: "Unit test: ExtractedTransaction.balance/merchant_normalized round-trip in tests/features/ingestion/test_normalizer.py"
Task: "Unit test: service passthrough of balance/merchant_normalized in tests/features/ingestion/test_service.py"
```

## Parallel Example: Foundational Phase

```bash
# Launch independent file moves together:
Task: "Move prompts.py + prompt_templates/ to agents/chunked_langgraph/"
Task: "Move chunking.py to agents/chunked_langgraph/"

# Launch the new renderer and its tests together (no dependency on the moves above):
Task: "Create agents/chunked_langgraph/markdown_render.py"
Task: "Unit tests for markdown_render.py in tests/features/ingestion/test_markdown_render.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1 (now including `balance`/`merchant_normalized`, T013-T020).
4. **STOP and VALIDATE**: confirm US1's Independent Test passes; this alone unblocks the backend
   integration work FR-001/FR-003 exist for (the "blocking integration problem" per spec.md's own
   priority rationale).
5. Coordinate T050 (backend tracking issue) even at this stage — FR-011's breaking-change coordination
   applies as soon as US1 ships, not only once every story is done.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → test independently → this is the MVP (matches spec.md's explicit P1 rationale).
3. US2 → test independently → completes the two P1 "blocking integration" stories together.
4. US3, US4 → test independently, any order → performance/reliability improvements, no contract
   change.
5. US5 → verification/documentation increment.
6. US6 → observability increment; land last per the file-overlap note above.
7. Polish (Phase 9) → cross-repo coordination tracking + final end-to-end validation before merge.

### Parallel Team Strategy

With multiple developers, after Foundational:

- Developer A: US1 → US2 (both touch `schemas.py`/prompt template/`service/normalize.py`; keep
  sequential within one owner to avoid merge conflicts on those files).
- Developer B: US3 (`graph.py`).
- Developer C: US4 (`chunking.py`).
- US5 (light) and US6 (widest-reaching, lands last) can go to whichever developer frees up first.

---

## Notes

- `[P]` tasks touch different files (or clearly separable regions) with no dependency on an
  incomplete task.
- `[Story]` labels map every user-story-phase task back to spec.md for traceability.
- Every test task is written to fail against the pre-change code — confirm the failure before
  starting the paired implementation task.
- T046/T050/T051 are the three places this plan's explicitly-tracked, requester-approved
  Principle III/FR-011 deviations must stay visible — do not let any of them quietly disappear.
- T015-T016/T018-T020 (US1) and T035 (US4) were added during `/speckit-analyze` remediation
  (2026-07-23) to close two coverage gaps found in the original task breakdown: FR-003
  (`balance`/`merchant_normalized`) had zero tasks, and SC-005 (chunking-strategy equivalence) had no
  verification task at all. Re-running `/speckit-analyze` after this edit should show 100% FR/SC
  coverage.
- Commit after each task or logical group; stop at any story checkpoint to validate independently.
