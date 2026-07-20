---

description: "Task list for feature implementation"
---

# Tasks: Structured Logging Setup

**Input**: Design documents from `/specs/012-structured-logging-setup/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Included. The project constitution (Principle I: Mandatory Automated
Testing) requires every feature to ship with automated, deterministic tests —
not optional for this feature.

**Organization**: Tasks are grouped by user story (from spec.md) to enable
independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every description

## Path Conventions

Single existing FastAPI project. Cross-cutting infrastructure lives under
`app/core/`; feature slices under `app/features/*`; tests mirror that under
`tests/core/` and `tests/integration/` (existing convention — see
`tests/core/test_config.py`, `tests/integration/test_chat_memory.py`).

---

## Phase 1: Setup

**Purpose**: No new project scaffolding is needed — this feature extends the
existing `app/` FastAPI service. Nothing to do here beyond confirming the
target files exist.

- [X] T001 Confirm `app/core/config.py`, `app/main.py`, and `pyproject.toml` are the current versions on branch `012-structured-logging-setup` (no scaffolding changes needed; proceed directly to Foundational)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared logging plumbing every user story depends on — the
structlog pipeline, config settings, and the non-negotiable redaction
backstop (Principle III applies unconditionally, not just to US3).

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Add `structlog` as a runtime dependency in `pyproject.toml` and refresh the lockfile with `uv lock`
- [X] T003 [P] Add `log_level: str = "INFO"` to `Settings` in `app/core/config.py`, with a fail-fast startup check (module-level, alongside the existing `RuntimeError` checks) that rejects any value not in `{DEBUG, INFO, WARNING, ERROR, CRITICAL}` (case-insensitive)
- [X] T004 [P] Add `log_debug_include_raw_content: bool = False` to `Settings` in `app/core/config.py`
- [X] T005 [P] Document `LOG_LEVEL` and `LOG_DEBUG_INCLUDE_RAW_CONTENT` in `.env.example`, following the existing commented-section style
- [X] T006 Create `app/core/logging.py`: configure `structlog` processors (UTC ISO-8601 timestamper, level adder, logger-name adder, JSON renderer) plus the stdlib-`logging` `ProcessorFormatter` bridge so libraries logging through stdlib `logging` (uvicorn, sqlalchemy) render in the same JSON format; expose `get_logger(name: str)` (depends on T002, T003)
- [X] T007 In `app/core/logging.py`, add a redaction processor to the pipeline built in T006 that matches field names against a fixed denylist (`api_key`, `token`, `password`, `authorization`, and any field ending in `_secret` or `_key`) and replaces their values with `"[REDACTED]"`, applied unconditionally regardless of configured `log_level` (depends on T006)
- [X] T008 Call the `app/core/logging.py` configuration function at import time of `app/main.py`, before `create_app()` builds the FastAPI instance (depends on T006)
- [X] T009 Disable uvicorn's built-in access log in the service's run configuration (the `uvicorn` invocation used to start `app.main:app`, e.g. in `Dockerfile`/`docker-compose`/run script) so it never emits its own plain-text access line alongside the structured one added in US1

**Checkpoint**: `get_logger(__name__)` is available service-wide and emits
redacted, structured JSON to stdout. User story implementation can now begin.

---

## Phase 3: User Story 1 - Diagnose a production error from logs alone (Priority: P1) 🎯 MVP

**Goal**: Every request produces a structured access-log line, and every
unhandled exception produces a structured error-log line with full
diagnostic detail, without crashing the process.

**Independent Test**: Trigger an unhandled error in any feature slice and
confirm a single log entry appears with severity, timestamp, originating
module, error message, and stack trace; confirm a completed request logs its
method/path/status/duration.

### Tests for User Story 1

> Write these first; confirm they fail against the Foundational-only code
> before implementing.

- [X] T010 [P] [US1] Unit test in `tests/core/test_logging.py`: a log entry emitted via `get_logger(__name__).info(...)` is a single valid JSON line containing `timestamp`, `level`, `logger`, and `event`
- [X] T011 [P] [US1] Unit test in `tests/core/test_request_logging.py`: given an active exception, a log call records `exception.type`, `exception.message`, and a non-empty `exception.stacktrace` at `error` severity
- [X] T012 [P] [US1] Integration test in `tests/integration/test_access_logging.py` (renamed from the originally planned `test_request_logging.py` — that basename collided with `tests/core/test_request_logging.py` under pytest's rootdir-based module naming): a completed request against a real route emits exactly one access-log entry with `http_method`, `http_path`, `http_status`, and `duration_ms`, and never a `body` field

### Implementation for User Story 1

- [X] T013 [US1] Create `app/core/request_logging.py` with `RequestLoggingMiddleware` (Starlette `BaseHTTPMiddleware`): times the request and, in a `finally` block, logs one access-log entry via `get_logger(__name__)` with `http_method`, `http_path`, `http_status`, `duration_ms` (depends on T006)
- [X] T014 [US1] In `RequestLoggingMiddleware` (`app/core/request_logging.py`), ensure an unhandled exception raised by `call_next` is logged at `error` severity with exception detail before propagating, so the process doesn't crash and the access-log line still fires with a failure status (depends on T013)
- [X] T015 [US1] Register `RequestLoggingMiddleware` via `app.add_middleware(...)` in `create_app()` in `app/main.py` (depends on T013)
- [X] T016 [P] [US1] Replace the ad hoc `import logging` / `logging.getLogger(__name__)` in `app/features/chat/service.py` with `from app.core.logging import get_logger` / `logger = get_logger(__name__)`
- [X] T017 [P] [US1] Replace the ad hoc `import logging` / `logging.getLogger(__name__)` in `app/features/ingestion/normalizer/graph.py` with `from app.core.logging import get_logger` / `logger = get_logger(__name__)`

**Checkpoint**: User Story 1 is fully functional and independently
testable — an engineer can diagnose a production error from stdout logs
alone.

---

## Phase 4: User Story 2 - Trace one request across multiple feature slices (Priority: P2)

**Goal**: Every log line produced while handling one request or background
job shares a single correlation identifier, distinct from concurrent
requests, including work spawned via `asyncio.gather` fan-out.

**Independent Test**: Issue a request that triggers multi-step processing
(chat turn or statement normalization run) and confirm every resulting log
line carries the same correlation identifier, distinct from a concurrent
unrelated request's.

### Tests for User Story 2

- [X] T018 [P] [US2] Unit test in `tests/core/test_request_logging.py`: `structlog.contextvars.bind_contextvars(correlation_id=...)` bound at request start is present on log entries emitted during that scope, and absent after `clear_contextvars()` runs
- [X] T019 [P] [US2] Integration test in `tests/integration/test_correlation_id.py`: two concurrent requests each produce log entries carrying exactly one `correlation_id`, and no entry carries the other request's id
- [X] T020 [P] [US2] Integration test in `tests/integration/test_correlation_id.py`: a request that triggers `asyncio.gather`-based fan-out (statement normalization chunk dispatch in `app/features/ingestion/normalizer/graph.py`) produces log entries from every spawned task carrying the same `correlation_id` as the originating request

### Implementation for User Story 2

- [X] T021 [US2] Extend `RequestLoggingMiddleware` in `app/core/request_logging.py` to mint a `uuid.uuid4()` correlation id at the start of `dispatch()`, bind it with `structlog.contextvars.bind_contextvars(correlation_id=...)`, and clear it with `structlog.contextvars.clear_contextvars()` in the existing `finally` block (depends on T013, T014)

**Checkpoint**: User Stories 1 and 2 both work independently — every log
line for a request/job is traceable back to that single unit of work.

---

## Phase 5: User Story 3 - Confirm logs never leak regulated data (Priority: P3)

**Goal**: Verify the unconditional redaction backstop from Foundational, and
add the explicit, default-off debug mode that may include raw LLM
prompt/completion and DB query content — gated so it can never turn on via a
production-safe default.

**Independent Test**: Exercise every feature slice's logging output at
default and at debug verbosity and confirm no PII, financial data, or secret
value appears, and that raw prompt/query content appears only when the
debug flag is explicitly enabled.

### Tests for User Story 3

- [X] T022 [P] [US3] Unit test in `tests/core/test_logging.py`: the redaction processor (T007) replaces the value of any field named `api_key`, `token`, `password`, `authorization`, or matching `*_secret`/`*_key` with `"[REDACTED]"`, at every severity level
- [X] T023 [P] [US3] Unit test in `tests/core/test_logging.py`: with `log_debug_include_raw_content` unset (default `False`), a call-site helper that would attach `prompt`/`completion`/`query` fields omits them entirely, even when `log_level=DEBUG`
- [X] T024 [P] [US3] Unit test in `tests/core/test_config.py`: starting the app with `log_debug_include_raw_content=True` emits exactly one `warning`-level log entry announcing raw-content logging is enabled

### Implementation for User Story 3

- [X] T025 [US3] Add a small gating helper to `app/core/logging.py` (e.g. `raw_content_fields(**fields) -> dict`) that returns the given fields only when `settings.log_debug_include_raw_content` is `True`, else `{}`; emit the one-time startup warning described in T024 from the same module at configuration time (depends on T006, T008)
- [X] T026 [P] [US3] Update the LLM-calling log statements in `app/features/chat/service.py` to attach prompt/completion content only via the T025 gating helper, logging metadata (model name, token counts, latency) unconditionally instead (depends on T025)
- [X] T027 [P] [US3] Update the LLM-calling log statements in `app/features/ingestion/normalizer/graph.py` to attach prompt/completion content only via the T025 gating helper, logging metadata (chunk index, char/token counts, latency) unconditionally instead (depends on T025)

**Checkpoint**: All three user stories are independently functional — logs
are structured, correlated, and verified free of regulated data by default.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validate the full feature end-to-end and confirm nothing
regressed.

- [X] T028 Run the `quickstart.md` validation steps against a locally running instance (`specs/012-structured-logging-setup/quickstart.md`) and confirm each step's expected outcome
- [X] T029 [P] Run `ruff check`, `black --check`, and `mypy` across all new/changed files (`app/core/logging.py`, `app/core/request_logging.py`, `app/core/config.py`, `app/main.py`, and the migrated feature files)
- [X] T030 [P] Run the full existing test suite (`pytest`) to confirm the `logging.getLogger` → `get_logger` migration in `app/features/chat/service.py` and `app/features/ingestion/normalizer/graph.py` introduced no regressions in their existing tests

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; extends the
  `RequestLoggingMiddleware` created in US1 (T013/T014), so in practice
  starts after US1's T013/T014 land, even though it introduces no new
  user-facing capability that requires all of US1 to be "done"
- **User Story 3 (Phase 5)**: Depends on Foundational only (T025 depends on
  T006/T008 from Foundational, not on US1/US2 work) — can proceed in
  parallel with US1/US2 if staffed separately
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests written and failing before implementation
- US1: middleware (T013) before exception handling (T014) before
  registration (T015); logger migrations (T016, T017) are independent of
  the middleware work and of each other
- US2: T021 depends on US1's T013/T014 already existing (it edits the same
  middleware)
- US3: gating helper (T025) before the two call-site updates (T026, T027),
  which are independent of each other

### Parallel Opportunities

- T003, T004, T005 (Foundational config/env-doc tasks) can run in parallel
- T010, T011, T012 (US1 tests) can run in parallel; T016, T017 (US1 logger
  migrations) can run in parallel with each other and with the middleware
  work (T013–T015)
- T018, T019, T020 (US2 tests) can run in parallel
- T022, T023, T024 (US3 tests) can run in parallel; T026, T027 (US3
  call-site updates) can run in parallel with each other
- US3 (Phase 5) can be staffed in parallel with US1/US2 (Phases 3–4) once
  Foundational is done, since T025 only depends on Foundational

---

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "Unit test log format in tests/core/test_logging.py"
Task: "Unit test exception logging in tests/core/test_request_logging.py"
Task: "Integration test access logging in tests/integration/test_access_logging.py"

# Logger migrations together (independent of middleware work):
Task: "Migrate app/features/chat/service.py to get_logger"
Task: "Migrate app/features/ingestion/normalizer/graph.py to get_logger"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational)
2. Complete Phase 3 (User Story 1)
3. **STOP and VALIDATE**: run the User Story 1 independent test — trigger an
   error, confirm the structured error and access-log lines
4. This alone already satisfies the feature's primary value: diagnosing a
   production error from logs

### Incremental Delivery

1. Setup + Foundational → shared logging plumbing ready
2. Add User Story 1 → validate independently → MVP
3. Add User Story 2 → validate correlation independently
4. Add User Story 3 → validate redaction/debug-gating independently
5. Polish: quickstart validation, lint/type/test suite

### Parallel Team Strategy

Once Foundational is complete: one developer takes US1 → US2 (they build on
the same middleware file), a second developer takes US3 in parallel (only
depends on Foundational). Both integrate cleanly since US2 and US3 touch
disjoint files (`request_logging.py` vs. `logging.py` + call sites).

---

## Notes

- [P] tasks touch different files with no unmet dependencies
- Tests are included per the project constitution's mandatory-testing
  principle, not left optional
- Redaction (T007) is implemented in Foundational, not deferred to US3,
  because Principle III's data-minimization guarantee is non-negotiable and
  applies from the very first log line — US3 verifies it and adds the
  opt-in debug-content capability on top
- Commit after each task or logical group; stop at any checkpoint to
  validate a story independently
