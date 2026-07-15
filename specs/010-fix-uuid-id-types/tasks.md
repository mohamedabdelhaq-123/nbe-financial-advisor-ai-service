---

description: "Task list for UUID Identifier Consistency"
---

# Tasks: UUID Identifier Consistency

**Input**: Design documents from `/specs/010-fix-uuid-id-types/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: FR-012/SC-005 require every existing test touching the affected identifier surfaces to be updated to UUID values and to keep passing. This is an update-existing-tests obligation, not a new-tests-first (TDD) obligation, so test-update tasks are folded into each story's implementation phase rather than a separate "write failing tests" sub-phase.

**Organization**: Tasks are grouped by user story (spec.md) to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths are exact and relative to the repository root.

## Path Conventions

Single project. Source under `app/`, tests under `tests/`, migrations under `migrations/versions/`.

---

## Phase 1: Setup

**Purpose**: No new project scaffolding is needed (existing dependencies cover every UUID type used — stdlib `uuid.UUID`, SQLAlchemy `Uuid`, Pydantic `UUID4`). This phase only confirms the working tree is ready.

- [X] T001 Confirm a clean working tree on branch `010-fix-uuid-id-types` and that `uv sync` completes with no dependency changes required (no new packages are introduced per `research.md` D10).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Amend the own-DB migration and re-provision so every user story has UUID-typed columns to build against. **No user story's own-DB work can be validated until this phase is complete.**

- [X] T002 Amend `migrations/versions/a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py`: change `ai_audit_log.user_id`, `ai_problem_statements.product_id`, `ai_recommendation_logs.user_id`, and `ai_recommendation_logs.product_id` from `sa.Integer()` to `sa.Uuid()` inside `upgrade()`. Do not add a new revision (research.md D2).
- [X] T003 Re-provision the local/dev own DB against the amended migration: `alembic downgrade base && alembic upgrade head` (or drop-and-recreate), per `quickstart.md` Step 0.
- [X] T004 Add a Testcontainers integration test in `tests/integration/test_migrations.py` asserting that after `alembic upgrade head` the four columns (`ai_audit_log.user_id`, `ai_problem_statements.product_id`, `ai_recommendation_logs.user_id`, `ai_recommendation_logs.product_id`) report `data_type = uuid` via `information_schema.columns` (SC-001, quickstart.md Step 0).

**Checkpoint**: Own-DB schema is UUID-typed end to end. User story implementation can now begin.

---

## Phase 3: User Story 1 - Privileged actions are attributed to the real user (Priority: P1) 🎯 MVP

**Goal**: Every chat turn's `user_id` flows as a UUID from the request through the audit log and the analysis agent's backend query, with no int/str coercion, and non-UUID `user_id` is rejected at the request boundary.

**Independent Test**: Send one chat turn with a UUID `user_id`, confirm the resulting `ai_audit_log` row stores that same UUID natively, and confirm a non-UUID `user_id` is rejected with 422 before any audit write.

### Implementation for User Story 1

- [X] T005 [P] [US1] In `app/features/audit/models.py`: change `AiAuditLog.user_id` from `Mapped[int | None] = mapped_column(Integer, nullable=True)` to `Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)`; add `import uuid` and swap the `Integer` import for `Uuid` from `sqlalchemy`.
- [X] T006 [P] [US1] In `app/core/audit.py`: change `record_audit()`'s `user_id` parameter from `int | None` to `uuid.UUID | None`; add `import uuid`.
- [X] T007 [US1] In `app/features/chat/schemas/request.py`: add a new `UserContext` model (`model_config = ConfigDict(extra="ignore")`, single field `user_id: UUID4`); change `ChatTurnRequest.user_id` from `int` to `UUID4`; change `ChatTurnRequest.initial_context` from `dict | None` to `UserContext | None`; update the class-level `examples` and the `user_id`/`initial_context` field `examples` to realistic UUID strings (e.g. `"7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d"`); import `UUID4` from `pydantic`.
- [X] T008 [US1] In `app/features/chat/state.py`: change `ConversationState.user_context` from `dict` to `UserContext`; import `UserContext` from `app.features.chat.schemas.request` (or `app.features.chat.schemas` if re-exported).
- [X] T009 [US1] In `app/features/chat/service.py`: change the `user_context: dict = {}` local (line 64) to hold a `UserContext | None`, assigning `request.initial_context` directly (already validated) instead of the raw dict; keep passing it into `state["user_context"]` unchanged in shape (dependent on T007, T008).
- [X] T010 [US1] In `app/features/chat/agents/analysis.py`: replace `user_id = state["user_context"].get("user_id")` with `user_id = state["user_context"].user_id if state["user_context"] else None` (attribute access on the typed `UserContext`, not `.get()`); drop the `str(user_id)` coercion at line 30 so the query reads `Transaction.user_id == user_id` directly (dependent on T008).
- [X] T011 [US1] In `tests/features/chat/test_chat.py`: change every `"user_id": 1` request-factory value (lines 13, 25, 38, 52, 76) to a realistic UUID4 string.
- [X] T012 [US1] In `tests/features/chat/test_streaming.py`: change `user_id=1` (line 60) to a realistic UUID4 string.
- [X] T013 [P] [US1] In `tests/integration/test_chat_memory.py`: change `"user_context": {"user_id": 1}` (line 44) to construct a `UserContext(user_id=<uuid4-string>)` (or the equivalent dict shape the state now expects), consistent with T008's typed `user_context` (SC-006, FR-013).
- [X] T014 [US1] Add/extend a test in `tests/features/chat/test_schemas.py` asserting `ChatTurnRequest(user_id=1001, ...)` (an int) raises `ValidationError`, and that a valid UUID4 string is accepted — covering FR-001's fail-fast rejection.
- [X] T015 [US1] Run `uv run pytest tests/features/chat/ tests/features/audit tests/integration/test_chat_memory.py tests/integration/test_migrations.py -k "not testcontainers or true"` (or the project's normal test invocation) and fix any remaining failures surfaced by the T005–T014 changes before moving to US2.

**Checkpoint**: User Story 1 is fully functional — audit rows carry UUIDs, non-UUID `user_id` is rejected at 422, and multi-turn continuity still resumes correctly.

---

## Phase 4: User Story 2 - Recommendations point at real products and show their real names (Priority: P2)

**Goal**: Every `product_id` the service holds — in its two own-DB tables, in the recommendations request/response, and in the chat widget payload — is a UUID, and the recommendation agent shows the real product title fetched from the backend `Products` table instead of the fabricated `"Product {id}"` placeholder.

**Independent Test**: Seed problem statements keyed by UUID `product_id`, trigger a recommendation reply, and verify the returned matches carry the same UUIDs and real product titles from the backend `Products` table — no placeholder, no bridging cast.

### Implementation for User Story 2

- [X] T016 [P] [US2] In `app/features/recommendations/models.py`: change `AiProblemStatement.product_id` from `Mapped[int] = mapped_column(Integer, nullable=False)` to `Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)`; change `AiRecommendationLog.user_id` and `AiRecommendationLog.product_id` from `Integer` to `Uuid` the same way; add `import uuid` and swap the `Integer` import for `Uuid`.
- [X] T017 [P] [US2] In `app/features/recommendations/schemas.py`: change `MatchRequest.user_id` from `int` to `UUID4`; change `ProductMatch.product_id` from `int` to `UUID4`; update all `examples` (class-level and field-level, including `MatchResponse`'s nested example) from integers (`1001`, `42`) to realistic UUID strings; import `UUID4` from `pydantic`.
- [X] T018 [US2] In `app/features/recommendations/service.py`: change `match()`'s `user_id: int = 0` parameter to `user_id: UUID | None = None`; inside the match-building loop, replace `product_name=f"Product {product_id}"` with a real title fetched from the backend `Products` table via `get_backend_session()` (same read-only pattern as `analysis.py`), falling back to a placeholder string (e.g. `"Product unavailable"`) if the backend session/query fails, per `research.md` D4 and `contracts/recommendations-match.md`'s "Backend outage behavior" section; import `uuid.UUID`, `app.backend_db.get_backend_session`, and `app.backend_db.models.Products` (or the generated model path) (dependent on T016, T017).
- [X] T019 [US2] In `app/features/recommendations/router.py`: no signature change needed beyond the types already flowing from `MatchRequest`/`match()` — verify `recommendation_match()` still type-checks cleanly after T017/T018 (no `int()`/`str()` casts to remove here; confirm none exist).
- [X] T020 [US2] In `app/features/chat/schemas/widgets.py`: change `ProductMatchPayloadItem.product_id` from `str` to `UUID4`; update the `examples` on `ProductMatchPayloadItem`, `ProductCardPayload`, and `ProductCardWidget` from `"sav-001"` / `"cc-002"` to realistic UUID strings; import `UUID4` from `pydantic`.
- [X] T021 [US2] In `app/features/chat/agents/recommendation.py`: replace `user_id = state["user_context"].get("user_id", 0)` with `user_id = state["user_context"].user_id if state["user_context"] else None` (typed attribute access); drop the `int(user_id) if user_id else 0` cast at the `match()` call; drop the `str(m.product_id)` bridging cast when building `ProductMatchPayloadItem` (both `product_id` and the source `m.product_id` are now UUID) (dependent on T008, T018, T020).
- [X] T022 [US2] In `app/features/recommendations/seed.py`: update the module docstring's documented JSON input format from `{"product_id": 1, "statement_text": "..."}` to a UUID string example, per `research.md` D6; no code change needed since `product_id` is passed through untouched into the now-UUID-typed model column (dependent on T016).
- [X] T023 [US2] In `tests/features/recommendations/test_recommendations.py`: change `user_id=10` and the `product_id == 1` / similar integer assertions to realistic UUID4 strings/values; update the mocked `Products` lookup so `product_name` assertions reflect a fetched title rather than the old placeholder shape.
- [X] T024 [P] [US2] In `tests/features/recommendations/test_seed.py`: change `{"product_id": 1, ...}` and `{"product_id": 2, ...}` (lines 11–12) to realistic UUID4 strings.
- [X] T025 [P] [US2] In `tests/features/recommendations/test_recommendation_router.py`: change `"user_id": 1` (lines 9, 27) to realistic UUID4 strings.
- [X] T026 [US2] In `tests/features/chat/test_recommendation_integration.py`: change `ProductMatch(product_id=1, ...)` / `ProductMatch(product_id=2, ...)` (lines 17–18) and `"user_context": {"user_id": 10}` (line 25) to realistic UUID4 values consistent with T008/T021; change the assertion `widget.payload.products[0].product_id == "1"` (line 47) to a UUID equality check against the matching UUID (no `str()` cast), per `contracts/chat-stream-amendment.md`'s "Test impact" section.
- [X] T027 [P] [US2] In `tests/features/chat/test_schemas.py`: change the `product_id` examples `"1"` (lines 85, 113) to realistic UUID4 strings.
- [X] T028 [US2] Run the recommendations and chat-recommendation test suites (`uv run pytest tests/features/recommendations tests/features/chat/test_recommendation_integration.py tests/features/chat/test_schemas.py`) and fix any remaining failures before moving to US3.

**Checkpoint**: User Stories 1 AND 2 both work independently — recommendations carry real UUIDs and real product titles end to end through the chat widget and the standalone match endpoint.

---

## Phase 5: User Story 3 - The public contract is internally consistent about every identifier (Priority: P3)

**Goal**: Every identifier-shaped example in the public request/response contract is a realistic UUID string, with no integer-like examples (`"1001"`, `"5001"`) remaining, and no field types change (analytics query paths already coerce correctly).

**Independent Test**: Read every identifier-shaped example in the analytics contract and confirm each is a realistic UUID string; `rg` for `"1001"|"5001"` in `app/features/analytics/schemas.py` returns no matches.

### Implementation for User Story 3

- [X] T029 [US3] In `app/features/analytics/schemas.py`: replace every `"1001"` (user_id) and `"5001"` (account_id) example — in `MonthlySummaryRequest`, `AnomalyCheckRequest`, `PostIngestionRequest`, `MonthlySummaryResult`, `AnomalyFlagResult`, and `PostIngestionResult`'s nested example — with realistic, distinct UUID4 strings. Field types (`str`) are unchanged (research.md D9).
- [X] T030 [P] [US3] Verify no other public contract file carries an integer-like identifier example: `rg --type=py '"1001"|"5001"' app/features/` returns no matches outside files already covered by T007/T017/T020/T029.

**Checkpoint**: All three user stories are independently functional; the public contract's examples are fully consistent with the backend's UUID ground truth.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final full-suite validation, lint/format/type-check, and the quickstart run-through.

- [X] T031 Run `uv run pytest` (full suite) and confirm it passes, including the new Testcontainers migration-column test from T004 (SC-005).
- [X] T032 [P] Run `uv run ruff check .` and `uv run black --check .`; fix any formatting/lint issues introduced by the type changes.
- [X] T033 [P] Run `uv run mypy`; confirm the `record_audit()` signature change (T006) ripples cleanly through the three `user_id=None` call sites (`app/features/transactions/service.py:76`, `app/features/ingestion/service/process.py:88`, `app/features/ingestion/service/normalize.py:130`) with no further code change needed.
- [X] T034 Walk through `quickstart.md` Steps 1–7 end to end against a locally re-provisioned own DB (seed → chat turn → audit row → non-UUID rejection → recommendation reply → analytics example check → full suite/lint/type-check) and confirm every "Expected outcome" holds.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS all user stories** — the own-DB columns must be UUID-typed before any story's DB-touching tests can pass.
- **User Story 1 (Phase 3)**: Depends on Foundational. No dependency on US2/US3.
- **User Story 2 (Phase 4)**: Depends on Foundational. Depends on US1's `UserContext` model (T007, T008) for `state["user_context"].user_id` attribute access in T021 — implement US1 first, or at minimum land T007/T008 before T021.
- **User Story 3 (Phase 5)**: Depends on Foundational only. Fully independent of US1/US2 (touches only `analytics/schemas.py`); can run in parallel with US1/US2 if staffed separately.
- **Polish (Phase 6)**: Depends on all three user stories being complete.

### Within Each User Story

- Model/schema changes before service/agent logic that consumes them.
- Service/agent logic before the tests that exercise it.
- Story implementation before that story's test-suite run task.

### Parallel Opportunities

- T005 and T006 (different files: `audit/models.py`, `core/audit.py`) can run in parallel.
- T016 and T017 (different files: `recommendations/models.py`, `recommendations/schemas.py`) can run in parallel.
- T024, T025, T027 (different test files) can run in parallel once their corresponding source changes land.
- US3 (Phase 5) can be worked entirely in parallel with US1/US2 — it touches only `analytics/schemas.py`.
- T032 and T033 (lint vs. type-check) can run in parallel.

---

## Parallel Example: User Story 1

```bash
# Launch independent model/helper edits together:
Task: "Change AiAuditLog.user_id to Uuid in app/features/audit/models.py"
Task: "Change record_audit()'s user_id param to uuid.UUID | None in app/core/audit.py"
```

## Parallel Example: User Story 2

```bash
# Launch independent model/schema edits together:
Task: "Change AiProblemStatement.product_id and AiRecommendationLog.{user,product}_id to Uuid in app/features/recommendations/models.py"
Task: "Change MatchRequest.user_id and ProductMatch.product_id to UUID4 in app/features/recommendations/schemas.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (amend migration, re-provision, add column-type test) — CRITICAL, blocks everything else.
3. Complete Phase 3: User Story 1 (audit attribution).
4. **STOP and VALIDATE**: run `quickstart.md` Steps 0–3 independently.
5. This alone brings the service into Principle III compliance even before US2/US3 land.

### Incremental Delivery

1. Setup + Foundational → own DB is UUID-typed.
2. Add User Story 1 → audit attribution correct → validate independently.
3. Add User Story 2 → recommendations correct end to end → validate independently.
4. Add User Story 3 → contract examples consistent → validate independently.
5. Phase 6 polish → full suite, lint, mypy, quickstart walkthrough.

### Parallel Team Strategy

With multiple developers, after Phase 2 (Foundational) completes:
- Developer A: User Story 1 (audit/chat).
- Developer B: User Story 3 (analytics examples) — fully independent, can start immediately.
- Developer C: User Story 2 (recommendations) — start once US1's `UserContext` (T007/T008) lands, since T021 depends on it.

---

## Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps task to specific user story for traceability.
- FR-012/SC-005: every test-file edit above is required for the full suite to stay green — none are optional.
- Commit after each task or logical group.
- Stop at any checkpoint to validate a story independently.
- The `UserContext`/`ConversationState` typed-state change (T008) was itself superseded by Phase 7 below (research.md D11) — noted here for the historical record rather than corrected in place, per this repo's accretive-clarification convention.

---

## Phase 7: Post-implementation amendment — decouple identity from conversation context (research.md D11)

**Context**: after Phase 3–6 shipped, review surfaced that T007's `UserContext` model (user_id-only, `extra="ignore"`) duplicated identity that already lived validated on `ChatTurnRequest.user_id`, and mislabeled `initial_context` — which is documented as generic conversation context (e.g. account summary), not an identity carrier. `is_first_turn` was also found to be a redundant, correctness-risky flag (research.md D11 has the full account). This phase reverses T007/T008's `UserContext` model in favor of decoupled identity, and removes `is_first_turn`.

**Independent Test**: send two chat turns on the same `conversation_id`, neither containing an `is_first_turn` field, and confirm both share checkpointer message history, `user_id`, and each produce their own correctly-attributed audit row.

- [X] T035 In `app/features/chat/schemas/request.py`: remove the `UserContext` model entirely; remove `is_first_turn` from `ChatTurnRequest`; revert `initial_context` to `dict | None` with an updated description clarifying it carries conversation context, never identity.
- [X] T036 In `app/features/chat/schemas/__init__.py`: remove the `UserContext` import/export.
- [X] T037 In `app/features/chat/state.py`: add a root-level `user_id: uuid.UUID` field to `ConversationState`; revert `user_context` to `dict | None`.
- [X] T038 In `app/features/chat/service.py`: remove the `is_first_turn`-gated branch; unconditionally call `graph.aget_state(config)` once per turn and restore `planner_answers`/`questions_asked`/`stage`/`user_context` from `prev_values` (empty for a genuinely new thread, so first-turn behavior is unchanged); set `state["user_id"] = request.user_id`; set `conversation_context` from `request.initial_context` when supplied, else carried forward from `prev_values.get("user_context")`.
- [X] T039 In `app/features/chat/agents/analysis.py`: read `user_id = state.get("user_id")` directly instead of unwrapping `state["user_context"].user_id`.
- [X] T040 In `app/features/chat/agents/recommendation.py`: read `user_id = state.get("user_id")` directly instead of unwrapping `state["user_context"].user_id`.
- [X] T041 [P] In `tests/features/chat/test_analysis_agent.py`, `tests/features/chat/test_recommendation_integration.py`, `tests/integration/test_chat_memory.py`: update state dicts to set `user_id` at the root and `user_context` to `None`/a plain dict, dropping all `UserContext(...)` construction.
- [X] T042 [P] In `tests/features/chat/test_streaming.py`: drop the now-meaningless `is_first_turn` kwarg from the `_request()` test helper.
- [X] T043 Run the full suite, ruff, black, and mypy; fix any fallout.
- [X] T044 Add `specs/010-fix-uuid-id-types/contracts/chat-request-amendment.md` documenting the breaking request-shape change; cross-reference it from `chat-stream-amendment.md` and from `specs/009-chat-streaming-contract/contracts/chat-stream.md`.
- [X] T045 Amend `spec.md` (new Clarifications session, FR-002 revision, new FR-014, User Story 1 Acceptance Scenario 2, Key Entities), `research.md` (mark D3 superseded, add D11), `data-model.md` (DTO/state tables, `UserContext` section), `quickstart.md` (Step 2 request example, new Step 2a), and `plan.md` (Constitution Principle VIII row, file-structure listing) to match the shipped shape.
- [X] T046 Validate live against a running dev instance: two turns on the same `conversation_id` with no `is_first_turn`, confirming shared message history, `user_id`, and per-turn audit rows (quickstart.md Step 2a).

**Checkpoint**: `ChatTurnRequest`/`ConversationState` carry identity exactly once (`user_id`, root-level, everywhere); `initial_context`/`user_context` carry only generic conversation context; `is_first_turn` no longer exists.
