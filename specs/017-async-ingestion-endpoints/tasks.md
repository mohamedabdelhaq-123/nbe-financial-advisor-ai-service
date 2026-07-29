---

description: "Task list for 017-async-ingestion-endpoints"
---

# Tasks: Async Ingestion Endpoints

**Input**: Design documents from `/specs/017-async-ingestion-endpoints/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/ingestion-jobs.md](contracts/ingestion-jobs.md),
[quickstart.md](quickstart.md)

**Tests**: Included, and not optional here — Constitution Principle I requires every feature to ship
with unit *and* integration tests, with integration tests running against a real Postgres via
Testcontainers. Note that SAQ's Postgres backend has no offline mode, so anything touching a real
queue is an integration test by construction; the status-derivation logic is deliberately factored as
a pure function so its behavior stays unit-testable.

**Organization**: Grouped by user story so each can be implemented, tested, and shipped independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US4, mapping to the user stories in spec.md
- Exact file paths are given in every task

## Path Conventions

Single project. Application code under `app/`, tests under `tests/`, migrations under
`migrations/versions/`. This feature's code lives in `app/features/ingestion/jobs/`.

---

## Phase 1: Setup

**Purpose**: Dependency and package skeleton

- [X] T001 Add `saq[postgres]` to `[project].dependencies` in `pyproject.toml` and refresh `uv.lock` with `uv lock`; confirm `psycopg`/`psycopg_pool` resolve from the existing pins rather than being upgraded
- [X] T002 [P] Create the package `app/features/ingestion/jobs/__init__.py` with a module docstring stating that SAQ owns the job record and this package owns only submission, status derivation, and the target→key mapping
- [X] T003 [P] Define the SAQ constants in `app/features/ingestion/jobs/queue.py`: `JOB_TIMEOUT = 0`, `JOB_TTL = 2_592_000`, `JOB_RETRIES = 1`, `JOB_HEARTBEAT`, `WORKER_CONCURRENCY` — each with a comment naming the SAQ default it overrides and what breaks at that default (research.md §2, §3)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Queue, worker, mapping table, and shared schemas — nothing in any user story works without these

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Implement `PostgresQueue` construction from own-DB settings in `app/features/ingestion/jobs/queue.py`, reusing the connection-string shape of `_psycopg_conn_string()` in `app/features/chat/checkpointer.py` rather than inventing a second one
- [X] T005 Implement `Worker` construction in `app/features/ingestion/jobs/queue.py` — job functions, `concurrency=WORKER_CONCURRENCY`, and the sweep timer that SC-005 depends on
- [X] T006 Wire queue connect and worker start/stop into the lifespan in `app/main.py`, next to the existing checkpointer setup; connection failures must propagate and abort startup, matching `checkpointer_setup_failed`
- [X] T007 **Verify the worker/uvicorn signal-handler interaction on a real running process** (research.md §1): start the service, send SIGTERM, confirm uvicorn still shuts down gracefully and the worker stops. If SAQ's handlers displace uvicorn's, apply a fallback from research.md §1 **before** continuing — this can invalidate the in-process topology and must not be discovered late
- [X] T008 [P] Create the `IngestionJobTarget` model in `app/features/ingestion/jobs/models.py` on `OwnBase` — `step`, `target_id` (plain `Uuid`, **no** `ForeignKey`), `job_key`, `submitted_at`, unique on `(step, target_id)` (data-model.md)
- [X] T009 [P] Create the Alembic migration for `ai_ingestion_job_targets` in `migrations/versions/`, including the unique constraint
- [X] T010 [P] Import `app.features.ingestion.jobs.models` in the `own_db_url` fixture in `tests/conftest.py` so `create_all` registers the table — the file already documents this exact trap for `AiAuditLog`
- [X] T011 [P] Define `JobSubmissionResponse` and `JobStatusResponse` in `app/features/ingestion/jobs/schemas.py` with `job_id` typed as `str` (SAQ's key, not a UUID) and epoch→timezone-aware-datetime conversion for the timestamps
- [X] T012 Implement target-existence validation in `app/features/ingestion/jobs/service.py` — `StatementFile` by `statement_id`, `StatementOcrResult` by `ocr_result_id`, projecting existence only, raising the same 404 details the blocking endpoints use (FR-003)
- [X] T013 [P] Extend `tests/integration/test_migrations.py` to assert `ai_ingestion_job_targets` exists after `alembic upgrade head`
- [X] T014 Integration test in `tests/integration/test_ingestion_jobs.py`: connecting the queue against Testcontainers Postgres creates `saq_jobs`, `saq_stats`, `saq_versions` — pins the assumption that SAQ self-migrates and no Alembic migration is needed for them

**Checkpoint**: Queue, worker, and mapping table exist; user stories can proceed

---

## Phase 3: User Story 1 - Submit extraction work and get an immediate acknowledgment (Priority: P1) 🎯 MVP

**Goal**: `POST /internal/ingestion/jobs/process` accepts a statement, acknowledges with a job reference before the work finishes, and the extraction runs to completion in the background.

**Independent Test**: Submit an extraction for a known statement, confirm the response arrives promptly with a job reference while work continues, and confirm afterwards that the extracted artifacts landed in object storage exactly as the blocking path produces them. Does not require the status route.

### Tests for User Story 1

- [X] T015 [P] [US1] Unit test in `tests/features/ingestion/test_jobs.py`: submitting a valid `statement_id` returns `202` with a `job_id`, `step: "process"`, `state: "queued"`, and enqueues exactly one job with the constants from T003 — queue mocked at the enqueue boundary
- [X] T016 [P] [US1] Unit test in `tests/features/ingestion/test_jobs.py`: an unknown `statement_id` returns `404` with detail `statement not found`, nothing is enqueued, and no mapping row is written (FR-003)

### Implementation for User Story 1

- [X] T017 [US1] Implement the `process` job function in `app/features/ingestion/jobs/tasks.py`: call the existing `process_statement()` unchanged, catch `HTTPException` and return `{"ok": false, "error": detail}`, return `{"ok": true, "result": ...}` on success, and let unexpected exceptions propagate to SAQ (research.md §5)
- [X] T018 [US1] Implement `submit_extraction_job()` in `app/features/ingestion/jobs/service.py`: validate the target (T012), enqueue with the T003 constants, insert the mapping row with `ON CONFLICT DO NOTHING`, return the job key. Dedup resolution is deliberately deferred to US4
- [X] T019 [US1] Add `POST /internal/ingestion/jobs/process` to `app/features/ingestion/router.py` returning `202`, with `responses={**ERROR_RESPONSES, 404: ...}`; leave the existing blocking routes untouched (FR-014)
- [X] T020 [US1] Integration test in `tests/integration/test_ingestion_jobs.py`: submit against real SAQ/Postgres with the pipeline mocked, run the worker, and assert the job reaches a terminal status carrying the same result body the blocking endpoint returns (SC-004)
- [ ] T021 [US1] Integration test: one `ingestion.process` audit row is written per async execution, matching what the blocking path writes (FR-015)
  - **Not done**: verifying a live audit row needs backend `statement_files` rows plus storage/MinerU, which the test fixtures don't provision. Covered indirectly by the delegation unit test in `tests/features/ingestion/test_jobs.py` (the async path calls the same `process_statement()` that writes the row) and by the quickstart's manual step.

**Checkpoint**: Extraction is submittable and runs in the background, verifiable through storage artifacts and the audit log

---

## Phase 4: User Story 2 - Check a job's progress and collect its result (Priority: P1)

**Goal**: `GET /internal/ingestion/jobs/{job_id}` reports queued/running/succeeded/failed with the full result or an actionable failure reason.

**Independent Test**: Submit a job, read its state while it runs, read it again after completion to collect the result, and read a deliberately failed job to confirm the failure reason is present and actionable.

### Tests for User Story 2

- [X] T022 [P] [US2] Unit test in `tests/features/ingestion/test_jobs.py` covering **every row** of the SAQ-status → contract-state table in data-model.md: `NEW`/`QUEUED` → `queued`, `ACTIVE` → `running`, `COMPLETE`+`ok` → `succeeded` with result, `COMPLETE`+`!ok` → `failed` with the pipeline's message, `FAILED`/`ABORTED`/`ABORTING` → `failed` with a generic message. Pure function, no queue involved
- [X] T023 [P] [US2] Unit test: a job whose key is unknown to SAQ produces `404 job not found`, indistinguishable from a never-existed reference

### Implementation for User Story 2

- [X] T024 [US2] Implement the status-derivation pure function in `app/features/ingestion/jobs/service.py` taking `(saq_status, envelope)` and returning `(state, result, error)` — keep it free of queue or session access so T022 needs no fixtures
- [X] T025 [US2] Implement `get_job_status()` in `app/features/ingestion/jobs/service.py`: look the key up in SAQ, convert epoch timestamps to timezone-aware UTC, and populate `JobStatusResponse` including `step` and `target_id`
- [X] T026 [US2] Add `GET /internal/ingestion/jobs/{job_id}` to `app/features/ingestion/router.py`, returning `200` for every known job regardless of outcome — a failed job is not an error status
- [X] T027 [US2] Ensure an unexpected exception surfaces as `failed` with a generic message while the stack trace goes to the service log only — SAQ stores a stack trace in `error` and it must never reach the caller (research.md §5)
- [X] T028 [US2] Audit every log/telemetry call added by this feature in `app/features/ingestion/jobs/`: job keys, steps, and states only — never result payloads or failure content derived from statement data (FR-006a)
- [X] T029 [US2] Integration test in `tests/integration/test_ingestion_jobs.py`: a job is readable the instant submission returns; transitions to `running` then `succeeded` are observable; repeated reads of a terminal job return identical content (FR-008)
- [X] T030 [US2] Integration test: a pipeline failure yields `failed` carrying the blocking endpoint's exact `detail` string for the same condition (FR-007)

**Checkpoint**: The async surface is complete and usable end-to-end for extraction — MVP boundary

---

## Phase 5: User Story 3 - Submit normalization work asynchronously (Priority: P2)

**Goal**: `POST /internal/ingestion/jobs/normalize` accepts an extraction result on the same terms as US1.

**Independent Test**: Submit a normalization job against a known extraction result, confirm the prompt acknowledgment, and later collect a result identical in content to the blocking normalization path.

### Tests for User Story 3

- [X] T031 [P] [US3] Unit test in `tests/features/ingestion/test_jobs.py`: submitting a valid `ocr_result_id` returns `202` with `step: "normalize"` and enqueues one job; an unknown id returns `404 ocr result not found` with nothing enqueued

### Implementation for User Story 3

- [X] T032 [US3] Implement the `normalize` job function in `app/features/ingestion/jobs/tasks.py`, calling the existing `normalize_statement()` unchanged and using the same envelope convention as T017
- [X] T033 [US3] Implement `submit_normalization_job()` in `app/features/ingestion/jobs/service.py`, sharing the submission flow with T018 rather than duplicating it
- [X] T034 [US3] Add `POST /internal/ingestion/jobs/normalize` to `app/features/ingestion/router.py`
- [X] T035 [US3] Integration test in `tests/integration/test_ingestion_jobs.py`: the collected result matches what the blocking normalize endpoint returns for the same input, including `normalized_json` shape and `model_used` (SC-004)
- [X] T036 [US3] Integration test: an in-flight extraction job for a statement does not suppress a normalization submission, and vice versa — the two steps are independent for dedup purposes

**Checkpoint**: Both pipeline steps are submittable asynchronously

---

## Phase 6: User Story 4 - Repeat submissions do not duplicate work (Priority: P3)

**Goal**: The same work submitted twice resolves to one execution, while a retry after a terminal outcome still starts a new job.

**Independent Test**: Submit the same target twice in quick succession and confirm the second is recognized as already in flight rather than starting a second execution.

### Tests for User Story 4

- [X] T037 [P] [US4] Unit test in `tests/features/ingestion/test_jobs.py`: with a mapping row whose job reports `ACTIVE`, a repeat submission returns that key without enqueuing; with a job reporting `COMPLETE`, it enqueues a new one

### Implementation for User Story 4

- [X] T038 [US4] Implement dedup resolution in the submission flow in `app/features/ingestion/jobs/service.py`: read the mapping row, ask SAQ for that key's status, return the key when `NEW`/`QUEUED`/`ACTIVE`, otherwise enqueue and update `job_key` (FR-010, FR-011, data-model.md's submission flow)
- [X] T039 [US4] Handle the aged-out case: a `job_key` unknown to SAQ is treated as terminal so a retry proceeds rather than deadlocking on a record that no longer exists
- [X] T040 [US4] Integration test in `tests/integration/test_ingestion_jobs.py`: two rapid submissions for one target return the same key and produce exactly one audit row (SC-006)
- [X] T041 [US4] Integration test for the case naive key-based dedup would break: after the first job is terminal **but its record is still present**, a resubmission returns a new key, the mapping row points at it, and the first job's terminal read is unchanged (FR-008, FR-011 — research.md §4)

**Checkpoint**: All four user stories are independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T042 Integration test in `tests/integration/test_ingestion_jobs.py`: a completed job's `expire_at` is ~30 days after `completed`, and the sweep deletes it once `expire_at` passes. **This assertion is the whole of FR-016** — with `ttl` at SAQ's 600s default it would silently become a 10-minute retention window, and nothing else in the suite would catch it (plan.md Principle III gate)
- [ ] T043 Integration test for restart behavior (FR-009 as amended): a job that had not started **resumes** and completes after a restart; a job that was executing is swept to `failed` and not re-executed. Measure the elapsed time to that sweep and adjust `JOB_HEARTBEAT` / the sweep timer until SC-005 holds
  - **Partly done**: both halves are tested (`test_a_job_queued_before_any_worker_exists_still_runs` and `test_job_orphaned_by_a_crash_is_swept_to_failed_not_left_running`), but the sweep test uses `heartbeat=1` for speed. The SC-005 timing with the production `JOB_HEARTBEAT`/`SWEEP_INTERVAL` constants has not been measured against a real restart.
- [X] T044 Integration test: a failure inside one job does not prevent other queued or running jobs from completing (FR-018)
- [X] T045 [P] Document the single-instance constraint and the in-process worker in the *Production deployment* section of `README.md` (FR-019), including why it matters rather than only that it applies
- [X] T046 [P] Add the single-instance comment to the `ai-service` block in `compose/docker-compose.prod.yml` — the file someone edits when about to add `deploy: replicas:` or `--workers`
- [X] T047 [P] Add OpenAPI descriptions to the three new routes in `app/features/ingestion/router.py` covering the polling model, the `202`-with-existing-key dedup behavior, and that a failed job is still `200`
- [X] T048 Run Ruff, Black (line length 100), and `mypy` over the new package and fix findings — CI gates on all three
- [ ] T049 Manually verify SC-003 and SC-007 per `quickstart.md`: drive the whole pipeline with a 60-second client timeout, and disconnect immediately after acknowledgment on the large-statement benchmark (3+ pages, 40+ transactions), confirming the job still completes and its result stays collectable
  - **Not done**: needs live MinerU, object storage, and a real statement; no such environment here.
- [ ] T050 Run the `quickstart.md` data-protection checks: grep logs for result content, confirm no Langfuse trace carries the job result, and confirm the status route returns `401` without a valid token (FR-006a, FR-013)
  - **Not done**: the log grep and Langfuse check need a real end-to-end run. The auth half is covered by unit tests asserting `401` on all three routes.
- [ ] T051 Write the PR description calling out the three Complexity Tracking items — the 30-day durable copy of transaction detail in `saq_jobs.result` (Principle III), SAQ migrating its own tables outside Alembic (Principle IV), and the slim mapping table — per the constitution's requirement that unavoidable deviations be justified explicitly in the PR
  - **Not done**: no PR exists yet.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — **blocks all user stories**
- **User Stories (Phases 3–6)**: All depend on Foundational
- **Polish (Phase 7)**: Depends on the stories it validates

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational
- **US2 (P1)**: Depends only on Foundational. Reads jobs US1 submits, but is testable against any job the queue holds, including one enqueued directly in a test
- **US3 (P2)**: Depends only on Foundational; reuses the submission flow from US1 (T033 shares T018's implementation) but is independently testable
- **US4 (P3)**: Depends on at least one submission path existing (US1 or US3), since it modifies the shared submission flow

### Critical path note

T007 (signal-handler verification) gates everything after it. If uvicorn and SAQ conflict over signal
handling, the in-process worker topology may have to change, which would rework T005–T006 and parts of
Phase 7. Do it before writing any story code.

### Parallel Opportunities

- T002 and T003 in parallel after T001
- T008–T011 and T013 in parallel once T004–T007 are settled (distinct files)
- All unit tests marked [P] within a story
- Once Foundational is done, US1/US2/US3 can be developed in parallel by different people; US4 should follow whichever submission path lands first
- T045, T046, T047 in parallel during Polish

## Parallel Example: Foundational

```bash
# After the queue/worker/lifespan tasks are settled:
Task: "Create IngestionJobTarget model in app/features/ingestion/jobs/models.py"
Task: "Create Alembic migration for ai_ingestion_job_targets in migrations/versions/"
Task: "Import the model module in tests/conftest.py"
Task: "Define JobSubmissionResponse/JobStatusResponse in app/features/ingestion/jobs/schemas.py"
Task: "Extend tests/integration/test_migrations.py with the new table assertion"
```

---

## Implementation Strategy

### MVP (User Story 1 + User Story 2)

Unlike the usual "US1 alone is the MVP" pattern, the deployable increment here is **US1 + US2**: a
submitted job that cannot be read back delivers nothing to the caller, which is why the spec gives
both stories P1 and says US2 "must ship with User Story 1". US1 alone is still independently
*testable* — via storage artifacts and audit rows — but it is not independently *useful*.

1. Phase 1: Setup
2. Phase 2: Foundational — **including T007's signal-handler verification**
3. Phase 3: US1
4. Phase 4: US2
5. **STOP and VALIDATE**: run the happy-path and timeout sections of `quickstart.md`, plus T042
   (retention) since it gates the Principle III position
6. Deploy — the backend can now migrate its extraction phase off the blocking call

### Incremental Delivery

1. Setup + Foundational → queue, worker, and mapping table exist
2. US1 + US2 → async extraction, end to end → deploy
3. US3 → async normalization → deploy
4. US4 → duplicate-submission safeguard → deploy
5. Polish → retention, restart, docs, and the manual SC-003/SC-007 validations

---

## Notes

- [P] = different files, no dependencies on incomplete work
- Three SAQ defaults are wrong for this feature (`timeout` 10s, `ttl` 600s, `heartbeat` 0). T003
  sets them, T042 and T043 prove they are right. A job dying at exactly ten seconds means T003 was
  not applied
- The blocking endpoints and `app/features/ingestion/service/` are not modified by any task here
  (FR-014); if a task seems to require it, the design has drifted
- Commit after each task or logical group
