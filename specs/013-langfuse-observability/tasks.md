---

description: "Task list for LLM Observability with Langfuse"
---

# Tasks: LLM Observability with Langfuse

**Input**: Design documents from `/specs/013-langfuse-observability/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/observability-config.md, quickstart.md (all present)

**Tests**: Included, not optional — Constitution Principle I mandates automated tests for every feature in this repo (mock-first for the LLM), overriding the generic "tests are optional" default from the tasks template.

**Organization**: Tasks are grouped by user story. Both User Story 1 and User Story 3 are P1 in spec.md; they are ordered US1 → US3 → US2 here (not the spec's listing order) because US3's acceptance criteria (zero-manual-setup startup, restart persistence, auth) build directly on the stack already being up and exercised in US1's phase — this avoids duplicating "bring the stack up" work across two phases. See the note under Phase 4.

## Path Conventions

Single existing FastAPI project. `app/core/` for cross-cutting modules, `app/main.py` for wiring, `tests/core/` for their tests, `compose/` for Docker Compose definitions — all per plan.md's Project Structure.

---

## Phase 1: Setup

**Purpose**: New dependencies, compose infrastructure, and configuration surface — no application behavior changes yet.

- [X] T001 [P] Add `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `openinference-instrumentation-langchain` to `pyproject.toml` dependencies and regenerate `uv.lock`
- [X] T002 [P] Add `LANGFUSE_ENABLED` (default `true`) / `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` to `.env.example`; per research.md §10, `LANGFUSE_ENABLED` is the on/off switch and host/keys default to match the local self-hosted stack's own headless-init values (`http://langfuse-web:3000` + the same dummy key pair `langfuse-web` seeds itself with) — matches contracts/observability-config.md §1
- [X] T003 [P] Create `compose/langfuse/docker-compose.yml` defining `langfuse-web`, `langfuse-worker`, `postgres`, `clickhouse`, `redis`, `minio`, per research.md §1: explicit, env-overridable pinned image versions (`${LANGFUSE_VERSION:-x.y.z}` etc., matching the `${MINERU_VERSION:-3.4.2}` convention already used in `compose/mineru/docker-compose.yml` — no `:latest` tags); `TZ=UTC` on `postgres` and `clickhouse`; `redis` started with `--maxmemory-policy noeviction`; only `langfuse-web` publishes port 3000 to the host, every other service is internal-only; include `LANGFUSE_INIT_*` passthrough env vars on `langfuse-web` for Langfuse's headless initialization (auto-seeds org/project/admin user/API-key pair, reusing `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` for the key pair — no manual UI signup) and a `LANGFUSE_AUTH_DISABLE_SIGNUP` passthrough env var (default `true`, since the account above is always seeded) so signup can be reopened without a compose edit if ever needed (used in T018); per research.md §9, tag all six services with the identical `profiles: ["observability"]` (opt-in, off by default — enabled via the explicit `--profile observability` CLI flag, not `COMPOSE_PROFILES` in `.env`, since that env var is Compose's "on by default" mechanism and the requirement here is the opposite); add a `dev-up-observability` Makefile target passing `--profile observability`
- [X] T004 Wire `compose/langfuse/docker-compose.yml` into `compose/docker-compose.yml` via the Compose spec's `include:` directive (depends on T003)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The core instrumentation/redaction machinery every user story depends on. Redaction is built here, not deferred — Constitution Principle III (v2.3.0) gives this feature's telemetry export zero exception, so no trace may leave the process unredacted, including the very first one used to validate US1.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Add `langfuse_enabled: bool = True`, `langfuse_host: str = "http://langfuse-web:3000"`, `langfuse_public_key: str = "pk-lf-..."`, `langfuse_secret_key: str = "sk-lf-..."` to the `Settings` class in `app/core/config.py`, following the existing `embedding_*`/`storage_s3_*` field pattern (data-model.md); per research.md §10, connection settings default non-blank to match the local self-hosted stack rather than empty/disabled; per research.md §11, add a module-level fail-fast check alongside the existing `STORAGE_S3_*`/`MINERU_API_URL` ones — `RuntimeError` if `langfuse_enabled` is `True` and any of `langfuse_host`/`langfuse_public_key`/`langfuse_secret_key` is empty
- [X] T006 [P] In `app/core/observability.py`, implement a pattern-redaction OTel `SpanProcessor` that masks card/email/phone-shaped values in span attribute strings before export (mirror the regex shapes in `app/features/chat/guards.py::strip_pii()` as a starting pattern set — do not import that function directly, it's feature-slice code and Principle V forbids a core module reaching into a feature slice) — research.md §3
- [X] T007 In `app/core/observability.py`, implement `configure()`: build an `OTLPSpanExporter` targeting `{langfuse_host}/api/public/otel`, authenticated via `OTEL_EXPORTER_OTLP_HEADERS` with `Authorization=Basic <base64(public_key:secret_key)>` — **percent-encode the `=` padding in the base64 value**, otherwise the OTel SDK's header parser mis-splits it and auth silently fails; wrap the exporter in a `BatchSpanProcessor` chained after the T006 redaction processor; call `LangChainInstrumentor().instrument()`; wrap the entire function body in a broad `try/except` that logs via `app.core.logging.get_logger` and never raises; return immediately (no-op) when `langfuse_enabled` is `False`; if enabled but any of the three connection settings is empty, log a warning and return without attempting instrumentation — defense-in-depth only, since T005's fail-fast check in `app/core/config.py` means this combination should already be unreachable by the time `configure()` runs (depends on T005, T006; gating updated per research.md §10/§11)
- [X] T008 In `app/main.py`, call `app_observability.configure()` immediately after the existing `app_logging.configure()` call (depends on T007)

**Checkpoint**: Foundation ready — user story work can begin.

---

## Phase 3: User Story 1 - Trace an end-to-end LLM request (Priority: P1) 🎯 MVP

**Goal**: Every LLM call made while handling a request is captured as a trace, calls within one logical operation nest under one trace, and failed calls are recorded rather than dropped.

**Independent Test**: Trigger a chat message and a multi-chunk normalization run; open the Langfuse UI and find a trace for each showing every LLM call made, in order, with prompt/response visible (redacted per Principle III) and a failed call recorded rather than silently missing.

### Tests for User Story 1

- [X] T009 [P] [US1] In `tests/core/test_observability.py`, test `configure()` is a no-op (no exception, no instrumentation attempted) when `langfuse_enabled` is `False`, is a no-op with a logged warning when enabled but any single connection setting is absent (defense-in-depth, research.md §11), and attempts instrumentation without raising when enabled with all three connection settings present pointing at a dummy/local endpoint. Per research.md §11, the primary enforcement moved to `app/core/config.py`: `tests/core/test_config.py` gets a parametrized `test_missing_langfuse_config_raises_when_enabled` (mirrors the existing `STORAGE_S3_*` fail-fast test) plus `test_langfuse_config_optional_when_disabled`.
- [X] T010 [P] [US1] In `tests/core/test_observability.py`, unit-test the T006 redaction processor: construct in-memory spans carrying card/email/phone-shaped attribute values, run them through the processor, assert those values are masked and unrelated attributes are untouched
- [X] T011 [US1] In `tests/core/test_observability.py`, with `configure()` active and an in-memory OTel span exporter substituted for the OTLP exporter, invoke a fake/mock chat model through the same LangChain call path `app/core/llm.py` uses and assert a span was captured — validates auto-instrumentation actually wraps LangChain calls with zero LLM-call-site changes; stays mock-first per Constitution Principle I (depends on T007)

### Implementation & Validation for User Story 1

- [ ] T012 [US1] Manual: `docker compose -f compose/docker-compose.yml --profile observability up --build` (or `make dev-up-observability`), with `.env`'s `LANGFUSE_*` vars set to the local pair (`.env.example`); confirm `ai-service`, `mineru-server`, and all six Langfuse services become healthy (quickstart.md step 1)
- [ ] T013 [US1] Manual: with `.env`'s `LANGFUSE_*` vars set to the local pair from T012/quickstart.md step 1 (auto-provisioned by `langfuse-web`'s headless init, no manual signup), trigger a real (`USE_MOCK_LLM=0`) chat request and a multi-chunk normalization run; confirm a trace appears for each within 10s, with correctly nested/ordered LLM calls and redacted-but-visible inputs/outputs (quickstart.md step 3; SC-001, SC-002, US1-AS1, US1-AS2)
- [ ] T014 [US1] Manual: trigger an LLM call failure (e.g. point `OPENAI_BASE_URL` at an unreachable host temporarily); confirm the trace records the failed step rather than omitting it (quickstart.md step 4; US1-AS3, FR-008)
- [ ] T015 [US1] Manual: stop `langfuse-web` and `langfuse-worker`, repeat the T013 request, confirm it still succeeds with no added latency or error; restart Langfuse and confirm tracing resumes (quickstart.md step 5; FR-005, SC-004)

**Checkpoint**: User Story 1 fully functional and independently deliverable as the MVP.

---

## Phase 4: User Story 3 - Run the observability stack locally without external dependencies (Priority: P1)

**Goal**: The observability stack starts, persists, and is access-controlled as part of the same local Compose workflow, with no external/hosted dependency.

**Independent Test**: Start all local services from a clean state with the `observability` compose profile enabled; confirm Langfuse is reachable and healthy with no manual account creation beyond what's documented, restart the stack, and confirm previously recorded traces are still present. Separately, confirm that starting without the profile brings up everything else with no trace of Langfuse's containers.

**Note on ordering**: Tied at P1 with US1. Placed second so its checks build on the stack T012/T013 already stood up and exercised, rather than repeating that setup.

- [ ] T016 [US3] Manual, two parts: (a) confirm a plain `docker compose -f compose/docker-compose.yml up --build` (no `--profile` flag) brings up `ai-service`/`mineru-server` only, with none of Langfuse's six containers running and the rest of the stack unaffected (quickstart.md step 1; US3-AS2); (b) confirm the T012 `--profile observability` startup required zero manual steps beyond the `.env` values already documented for other services — no separate signup, hosted account, or external network dependency for the observability tool itself; specifically, confirm `langfuse-web`'s headless init (T003/contract §1) seeded the org/project/admin account/API-key pair automatically, with no browser-based onboarding at any point (quickstart.md step 1; SC-003, FR-003, US3-AS1)
- [ ] T017 [US3] Manual: `docker compose restart langfuse-web langfuse-worker postgres clickhouse redis minio` (the Langfuse-owned services only, not this repo's own `postgres`); confirm the traces recorded in T013 remain visible afterward (quickstart.md step 6; US3-AS3, FR-004)
- [ ] T018 [US3] Manual: confirm the Langfuse UI at `localhost:3000` requires the admin login seeded by headless init (`LANGFUSE_INIT_USER_EMAIL`/`LANGFUSE_INIT_USER_PASSWORD`) and rejects unauthenticated access to trace data; confirm `LANGFUSE_AUTH_DISABLE_SIGNUP` defaults to `true` (wired in T003) so self-service signup is closed out of the box, with no post-setup step required (FR-007)

**Checkpoint**: Both P1 stories independently functional.

---

## Phase 5: User Story 2 - Monitor cost and usage across the service (Priority: P2)

**Goal**: Usage/cost figures in the Langfuse dashboard are filterable/groupable by the feature or flow that generated them.

**Independent Test**: After traces exist for ≥2 features, open Langfuse's usage view and confirm token/request counts can be broken down by originating feature over a selected time range.

- [X] T019 [US2] In `app/core/request_logging.py`, bind a module-level `current_feature: ContextVar[str | None]` from `request.url.path`'s segment after `/internal/`, set alongside the existing `correlation_id` binding and cleared in the same `finally` block (research.md §7)
- [X] T020 [US2] In `app/core/observability.py`, extend the T006 redaction processor to also read `current_feature` and stamp it onto every processed span as a Langfuse-recognized attribute before export (depends on T006, T019)
- [X] T021 [P] [US2] In `tests/core/test_request_logging.py`, assert `current_feature` reflects the active request's path segment and resets to `None` after the request completes, including across two sequential requests with different paths
- [X] T022 [P] [US2] In `tests/core/test_observability.py`, assert the processor stamps the current feature onto spans processed during a request, and stamps nothing (or an explicit "unknown" sentinel) when invoked outside any request context
- [ ] T023 [US2] Manual: after producing traces from ≥2 distinct features (e.g. the chat and normalization traces from T013), open Langfuse's usage/dashboard view and confirm token/request counts are filterable/groupable by originating feature over a selected time range (quickstart.md step 7; US2-AS1, US2-AS2, SC-005)

**Checkpoint**: All user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T024 [P] Document the new Langfuse UI (`http://localhost:3000`) in `README.md`'s "Running locally" section
- [X] T025 [P] Run Ruff, Black, and mypy over all new/edited files: `app/core/observability.py`, `app/core/config.py`, `app/core/request_logging.py`, `app/main.py`, `tests/core/test_observability.py`, `tests/core/test_request_logging.py`
- [ ] T026 Run the full quickstart.md validation (all 7 steps) end-to-end as the final acceptance gate

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001, T002, T003 can start immediately in parallel; T004 depends on T003.
- **Foundational (Phase 2)**: Depends on Setup completion (T005 needs nothing from Setup directly, but T007 assumes the dependencies from T001 are installed). BLOCKS all user stories.
- **User Stories (Phase 3–5)**: All depend on Foundational (Phase 2) completion.
  - US3 (Phase 4) depends on US1 (Phase 3) having stood up and exercised the stack (T012/T013) — not independent of US1 in execution order, only in principle.
  - US2 (Phase 5) can start any time after Foundational, independently of US1/US3, but its manual validation (T023) is more meaningful once US1 has produced real traces.
- **Polish (Phase 6)**: Depends on all desired user stories being complete.

### Within Each User Story

- Tests (T009–T011, T021–T022) before/alongside their implementation, per Constitution Principle I.
- Manual quickstart validations are ordered last in each phase since they exercise the code the automated tests already cover.

### Parallel Opportunities

- Setup: T001, T002, T003 in parallel.
- Foundational: T006 in parallel with T005 (different files); T007 depends on both.
- US1 tests: T009, T010 in parallel; T011 depends on T007 (Foundational) only.
- US2: T021, T022 in parallel (different files); both depend on T019/T020 being implemented first.
- Polish: T024, T025 in parallel.

---

## Parallel Example: Foundational Phase

```bash
# Launch in parallel — different files, no dependency between them:
Task: "Add langfuse_host/public_key/secret_key settings in app/core/config.py"
Task: "Implement the pattern-redaction SpanProcessor in app/core/observability.py"

# Then, once both land:
Task: "Implement configure() in app/core/observability.py (depends on both above)"
```

## Parallel Example: User Story 1 Tests

```bash
Task: "configure() no-crash test in tests/core/test_observability.py"
Task: "Redaction processor unit test in tests/core/test_observability.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (redaction is not optional here — see Phase 2 purpose note)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Run T012–T015 manually
5. This is the MVP — a working, redacted, fail-open trace pipeline for every existing feature, visible in Langfuse

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. User Story 1 → validate → MVP demoable
3. User Story 3 → validate stack persistence/auth on top of the already-running stack
4. User Story 2 → validate feature-attributed usage dashboard
5. Polish

---

## Notes

- [P] tasks touch different files with no dependency between them.
- [Story] labels map tasks to spec.md's user stories for traceability.
- Redaction (T006/T007) is Foundational, not story-specific — Constitution Principle III (v2.3.0) gives this feature's export path no exception, so it cannot be deferred past the first trace produced for US1's own validation.
- All "Manual" tasks are quickstart.md-driven validation steps, not automatable per Constitution Principle I's mock-first LLM rule (they require a real, non-mock LLM call and a running Langfuse instance).
