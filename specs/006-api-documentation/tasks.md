---

description: "Task list template for feature implementation"
---

# Tasks: API Documentation

**Input**: Design documents from `/specs/006-api-documentation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: None added — per research.md §3, this feature introduces no new runtime behavior
(only descriptions, examples, and typed response models on routes that already require the
same `require_token` dependency they always have), so the existing test suite is sufficient.
Documentation *completeness* (FR-006) is a manual PR-review responsibility (checklist:
contracts/openapi-enrichment-contract.md), not a CI gate — do not add tests that assert every
field/endpoint has a description or example.

**Organization**: Tasks are grouped by user story (US1/US2, priorities P1/P2 per spec.md) so
each can be delivered and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2)
- Every task includes an exact file path

---

## Phase 1: Setup

**Purpose**: Confirm the environment is ready — this feature adds no new dependencies.

- [X] T001 Confirm dependencies are current with `uv sync` at repo root (no new packages
      required — FastAPI ≥0.115 and Pydantic v2 already provide every mechanism this feature
      uses, per research.md item 1)

**Checkpoint**: Environment ready — no blocking setup work beyond this.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared error-response schema used by every endpoint task in every user story.

**⚠️ CRITICAL**: T002 MUST complete before any per-endpoint task in Phase 3 (US1), since every
one of them adds `responses={401: ..., 422: ...}` to a route.

- [X] T002 Add a shared `ERROR_RESPONSES` dict (401 → `{"detail": "Invalid or missing token"}`
      body per `app/core/security.py`'s `require_token`; 422 → FastAPI's built-in validation
      error shape) to `app/core/security.py`, for import into every feature router's
      `responses=` parameter (contracts/openapi-enrichment-contract.md items 4–5)

**Checkpoint**: Foundation ready — per-endpoint enrichment tasks (US1) can now proceed in
parallel across feature slices.

---

## Phase 3: User Story 1 - Integrate against a documented endpoint without reading source (Priority: P1) 🎯 MVP

**Goal**: Every `/internal/*` endpoint's OpenAPI operation carries a purpose description, a
concrete request/response schema (no untyped `dict`/`Any`), a 401/422 error entry, and at least
one example — satisfying SC-001/SC-002/SC-003.

**Independent Test**: Open `/docs`, pick any `/internal/*` operation, and confirm a developer
can construct a valid request/response expectation using only what's shown, per data-model.md's
endpoint inventory.

### Implementation for User Story 1

- [X] T003 [P] [US1] Add `Field(description=..., examples=[...])` to every field of
      `ChatTurnRequest` in `app/features/chat/schemas.py`, using synthetic non-PII values
      (Constitution III)
- [X] T004 [US1] Add a docstring description and
      `responses={200: {"content": {"text/event-stream": {...}}}, **ERROR_RESPONSES}` (per
      research.md §2 and contracts/openapi-enrichment-contract.md) to `POST /internal/chat` in
      `app/features/chat/router.py` (depends on: T002, T003)
- [X] T005 [P] [US1] Add `Field(description=..., examples=[...])` to every field of
      `MonthlySummaryRequest`, `AnomalyCheckRequest`, `PostIngestionRequest`,
      `MonthlySummaryResult`, `AnomalyFlagResult` in `app/features/analytics/schemas.py`; add a
      new `PostIngestionResult` model matching the actual
      `{"summary": ..., "recurring_charges": [...], "anomalies": [...]}` shape returned by
      `run_post_ingestion` (data-model.md analytics section)
- [X] T006 [US1] Add `response_model=MonthlySummaryResult`, a docstring description, and
      `responses={**ERROR_RESPONSES}` to `POST /internal/analyze/monthly-summary` in
      `app/features/analytics/router.py` (depends on: T002, T005)
- [X] T007 [US1] Add `response_model=list[AnomalyFlagResult]`, a docstring description, and
      `responses={**ERROR_RESPONSES}` to `POST /internal/analyze/anomaly-check` in
      `app/features/analytics/router.py` (depends on: T002, T005)
- [X] T008 [US1] Add `response_model=PostIngestionResult`, a docstring description, and
      `responses={**ERROR_RESPONSES}` to `POST /internal/analyze/post-ingestion` in
      `app/features/analytics/router.py` (depends on: T002, T005)
- [X] T009 [P] [US1] Add `Field(description=..., examples=[...])` to every field of
      `NextQuestionRequest`, `GeneratePlanRequest`, `PlanQuestion`, `GeneratePlanResponse`,
      `BudgetAllocation` in `app/features/plan/schemas.py`; add a new `NextQuestionResponse`
      model (`question: PlanQuestion | None`) matching the actual `{"question": ...}` shape
      returned by `/plan/question` (data-model.md plan section)
- [X] T010 [US1] Add `response_model=NextQuestionResponse`, a docstring description, and
      `responses={**ERROR_RESPONSES}` to `POST /internal/plan/question` in
      `app/features/plan/router.py` (depends on: T002, T009)
- [X] T011 [US1] Add a docstring description and `responses={**ERROR_RESPONSES}` to
      `POST /internal/plan/generate` in `app/features/plan/router.py` (already has
      `response_model=GeneratePlanResponse`) (depends on: T002, T009)
- [X] T012 [P] [US1] Add `Field(description=..., examples=[...])` to every field of
      `ProcessStatementRequest`, `ProcessStatementResult`, `NormalizeStatementRequest`,
      `NormalizeStatementResult` in `app/features/ingestion/schemas.py`
- [X] T013 [US1] Add `responses={**ERROR_RESPONSES}` to `POST /internal/ingestion/process` and
      `POST /internal/ingestion/normalize` in `app/features/ingestion/router.py` (docstrings
      already exist on both routes) (depends on: T002, T012)
- [X] T014 [P] [US1] Add `Field(description=..., examples=[...])` to every field of
      `MatchRequest`, `ProductMatch`, `MatchResponse` in
      `app/features/recommendations/schemas.py`
- [X] T015 [US1] Add a docstring description and `responses={**ERROR_RESPONSES}` to
      `POST /internal/recommendations/match` in `app/features/recommendations/router.py`
      (already has `response_model=MatchResponse`) (depends on: T002, T014)

**Checkpoint**: All 9 `/internal/*` endpoints are fully self-documented. US1 is independently
testable and deliverable now.

---

## Phase 4: User Story 2 - Documentation stays truthful as the API evolves (Priority: P2)

**Goal**: Documentation gaps are visible to a PR reviewer, and there is a concrete checklist to
review against — satisfying FR-006 as a manual review responsibility (not an automated gate, per
the clarified spec decision).

**Independent Test**: Add a field to an existing request/response model without a `Field`
description, confirm it renders as an empty/generic entry in `/docs` (inherent Swagger UI
behavior — no new code required) rather than being indistinguishable from a documented field,
per spec.md's Edge Cases.

### Implementation for User Story 2

- [X] T016 [US2] Add a short "API Documentation" note to `README.md`'s existing Phase 2 API
      surface section: point integrators at `/docs` and point reviewers at
      `specs/006-api-documentation/contracts/openapi-enrichment-contract.md` as the completeness
      checklist for any new or changed `/internal/*` endpoint

**Checkpoint**: Both user stories are independently functional. No further code changes are
needed for US2 — the "no drift" property (FR-005) is inherent to US1's approach (schema derived
live from `response_model`/`Field`, never a hand-authored copy).

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final verification across both stories.

- [X] T017 [P] Run `uv run ruff check .`, `uv run black --check .`, and `uv run mypy app` across
      every file touched in T003–T016
- [X] T018 Run the full test suite with `uv run pytest` to confirm no regressions (in
      particular that `tests/features/test_auth_matrix.py`'s existing 8 `/internal/*` auth
      assertions and its 2 `PUBLIC_ENDPOINTS` assertions for `/health`/`/ready` still pass
      unchanged)
- [X] T019 Execute quickstart.md end-to-end: start the app, do the manual `/docs` walkthrough
      for all 9 endpoints (step 2), the SSE-endpoint check (step 3), and the full test run
      (step 4)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — T002 BLOCKS every endpoint task in Phase 3
- **User Story 1 (Phase 3)**: Depends on Foundational (T002) only — independent of US2
- **User Story 2 (Phase 4)**: No code dependency on US1, but conceptually documents US1's
  output, so it's sequenced last for review clarity
- **Polish (Phase 5)**: Depends on both user stories being complete

### Parallel Opportunities

- T003, T005, T009, T012, T014 (all `schemas.py` field-annotation tasks across the 5 slices) can
  run in parallel — different files, no shared state
- T017 (lint/format/typecheck) can run in parallel with T018/T019 (runtime verification)

---

## Parallel Example: User Story 1

```bash
# Launch all 5 slices' schema-annotation tasks together (different files):
Task: "Add Field(description=..., examples=[...]) to ChatTurnRequest in app/features/chat/schemas.py"
Task: "Add Field(description=..., examples=[...]) to analytics request/result models in app/features/analytics/schemas.py, plus new PostIngestionResult"
Task: "Add Field(description=..., examples=[...]) to plan request/response models in app/features/plan/schemas.py, plus new NextQuestionResponse"
Task: "Add Field(description=..., examples=[...]) to ingestion request/result models in app/features/ingestion/schemas.py"
Task: "Add Field(description=..., examples=[...]) to recommendations request/response models in app/features/recommendations/schemas.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational — T002)
2. Complete Phase 3 (US1) — all 9 endpoints enriched
3. **STOP and VALIDATE**: browse `/docs`, confirm every endpoint is self-explanatory
   (quickstart.md step 2)

### Incremental Delivery

1. Setup + Foundational → shared error-response constant ready
2. Add US1 → validate independently → richer `/docs` content
3. Add US2 → validate independently → reviewer checklist in place, README points at it
4. Polish → lint/format/typecheck/full-suite/quickstart pass

### Parallel Team Strategy

With multiple developers, after Foundational (T002):

- Developer A: US1 (Phase 3) — all schema/router enrichment across the 5 slices
- Developer B: US2 (Phase 4) — README note (small, can start any time)

---

## Notes

- [P] tasks touch different files with no dependency on an incomplete task
- [Story] label maps each task to its user story for traceability
- Every task above already names its exact file path — no additional context should be needed
  to execute it
- No automated "documentation completeness" test exists anywhere in this task list — per
  research.md §3, that is deliberately left as a manual PR-review responsibility so as not to
  contradict the clarified FR-006 decision
