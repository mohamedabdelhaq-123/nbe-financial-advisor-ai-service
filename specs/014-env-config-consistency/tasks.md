# Tasks: Consistent, Fault-Tolerant Environment Configuration

**Input**: Design documents from `/specs/014-env-config-consistency/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/env-var-contract.md, quickstart.md

**Tests**: Included — spec.md's User Story 1 acceptance scenarios require per-group validators to be independently testable (FR-003), so unit tests for those validators are part of the work, not optional polish.

**Organization**: Tasks are grouped by user story per spec.md's priorities (US1/US2 both P1, US3 P2, US4 P3). A Foundational phase precedes all of them because every story depends on the same underlying `Settings` restructuring (new group/field names) — none of the four stories can be implemented, let alone tested, against the old flat field names.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- File paths are exact and relative to `nbe-financial-advisor-ai-service/` unless prefixed `deploy/`, which is `nbe-financial-advisor-backend/deploy/`.

---

## Phase 1: Setup

**Purpose**: Confirm no new dependencies are needed before touching code.

- [X] T001 Confirm `pydantic`/`pydantic-settings` versions pinned in `pyproject.toml` already support `env_nested_delimiter`, `model_validator(mode="after")`, and `SecretStr` (all pydantic v2 core features — expected no version bump; if a bump is needed, update `pyproject.toml` and `uv.lock` via `uv lock`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Restructure `Settings` into the nested groups from data-model.md and rename every consuming call site, with behavior otherwise unchanged (no new validation, no `SecretStr` yet — those are US1/US3). This is the prerequisite every user story needs just to compile and run.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete and the existing test suite passes against the renamed fields.

- [X] T002 Rewrite `app/core/config.py`: introduce nested `BaseModel` groups `ChatModelSettings`, `EmbeddingsSettings`, `OwnDbSettings`, `BackendDbSettings`, `StorageSettings`, `MinerUSettings`, `LangfuseSettings`, `LoggingSettings` per data-model.md's field tables, mounted on `Settings` as `chat_model`, `embeddings`, `own_db`, `backend_db`, `storage`, `mineru`, `langfuse`, `logging`; set `model_config = SettingsConfigDict(env_nested_delimiter="__", env_file=".env", extra="ignore")`; keep `ai_service_token` as a flat field on `Settings`. `ChatModelSettings`' and `MinerUSettings`' mock fields are named `use_mock` (briefly renamed to `mock_enabled` during planning, reverted post-implementation — research.md §8). Preserve every current default value exactly (including `own_db`'s current `"appdb"`/`"appuser"`/`"apppass"` — those defaults are removed in T019, not here). Do not move any of today's top-level `if`/`RuntimeError` validation blocks yet — leave them as-is, updated only to reference the new nested paths (e.g. `settings.chat_model.openai_api_key` instead of `settings.openai_api_key`)
- [X] T003 In `app/core/config.py`, update `own_database_url`/`backend_database_url` properties to read from the new grouped field paths (`self.own_db.postgres_user`, etc.); `backend_database_url` stays `str | None` for now (becomes required/non-Optional in T020)
- [X] T004 [P] Update `chat_model` group call sites to the new `settings.chat_model.*` paths (`use_mock`, `openai_base_url`, `openai_api_key`, `model_name`, `normalization_max_parallel_chunks`, `normalization_chunk_max_tokens`) in: `app/core/llm.py`, `app/features/chat/agents/analysis.py`, `app/features/chat/agents/maestro.py`, `app/features/chat/graph.py`, `app/features/chat/service.py`, `app/features/chat/summarize.py`, `app/features/ingestion/normalizer/__init__.py`, `app/features/ingestion/normalizer/graph.py`, `app/features/ingestion/normalizer/mock.py`, `app/features/plan/service.py`
- [X] T005 [P] Update `embeddings` group call sites to the new `settings.embeddings.*` paths (`base_url`, `api_key`, `model_name`, `dimensions`) in: `app/core/embedding.py`, `app/features/embed/router.py`
- [X] T006 [P] Update `own_db` group call sites to the new `settings.own_db.*` paths in: `app/features/chat/checkpointer.py`, `app/core/db.py` (via `settings.own_database_url`, unchanged call shape), `app/features/recommendations/seed.py` (via `settings.own_database_url`)
- [X] T007 [P] Update `backend_db` group call site in: `app/backend_db/__init__.py` (via `settings.backend_database_url`, unchanged call shape at this point)
- [X] T008 [P] Update `storage` group call sites to the new `settings.storage.*` paths (`s3_bucket`, `s3_endpoint_url`, `s3_region`, `s3_access_key`, `s3_secret_key`, `s3_use_path_style`, `s3_ocr_bucket`) in: `app/core/storage.py`, `app/features/ingestion/service/process.py`, `app/features/ingestion/service/normalize.py`
- [X] T009 [P] Update `mineru` group call sites to the new `settings.mineru.*` paths (`use_mock`, `api_url`, `api_key`) in: `app/core/system.py`, `app/features/ingestion/mineru_client.py`
- [X] T010 [P] Update `langfuse` group call sites to the new `settings.langfuse.*` paths (`enabled`, `host`, `public_key`, `secret_key`) in: `app/core/observability.py`
- [X] T011 [P] Update `logging` group call sites to the new `settings.logging.*` paths (`level`, `debug_include_raw_content`) in: `app/core/logging.py`
- [X] T012 Update `.env.example` variable names to the new `GROUP__FIELD` scheme per data-model.md's old→new mapping (rename only — do not yet add the missing `BACKEND_DB__NAME`, that's T041)
- [X] T013 Update `compose/docker-compose.prod.yml`'s pinned `environment:` keys (`POSTGRES_HOST`, `BACKEND_DB_HOST`, `STORAGE_S3_*`, `USE_MOCK_LLM`→`CHAT_MODEL__USE_MOCK`, `USE_MOCK_MINERU`→`MINERU__USE_MOCK`, etc.) to the new `GROUP__FIELD` names, same literal values
- [X] T014 Update `deploy/docker-compose.yml`'s `ai-service` `environment:` block (lines ~204-241) to the new `GROUP__FIELD` names, same `${VAR:-default}` values/defaults, and `deploy/.env.example` for any of those vars it documents (research.md §7, contracts/env-var-contract.md §4)
- [X] T015 Update `tests/conftest.py`'s `os.environ.setdefault(...)` calls to the new `GROUP__FIELD` names for the vars it currently fabricates (`USE_MOCK_LLM`→`CHAT_MODEL__USE_MOCK`, `OPENAI_BASE_URL`→`CHAT_MODEL__OPENAI_BASE_URL`, `OPENAI_API_KEY`→`CHAT_MODEL__OPENAI_API_KEY`, `MODEL_NAME`→`CHAT_MODEL__MODEL_NAME`, `STORAGE_S3_BUCKET`→`STORAGE__S3_BUCKET`, `STORAGE_S3_ACCESS_KEY`→`STORAGE__S3_ACCESS_KEY`, `STORAGE_S3_SECRET_KEY`→`STORAGE__S3_SECRET_KEY`, `USE_MOCK_MINERU`→`MINERU__USE_MOCK`), keeping the same fabricated values
- [X] T016 Run `uv run pytest tests -q --ignore=tests/integration` and confirm the existing suite passes unchanged against the renamed fields (behavior-preserving refactor checkpoint — no new tests yet)

**Checkpoint**: Foundation ready — `Settings` is grouped and renamed everywhere, existing tests pass, no new validation or masking behavior yet. User story implementation can now begin.

---

## Phase 3: User Story 1 - Fail fast with an actionable message on misconfiguration (Priority: P1) 🎯 MVP

**Goal**: Every required configuration group produces an immediate, named startup failure when unset or left at a placeholder — closing the gap for `own_db` (had no check) and `backend_db` (was optional, now required per the resolved clarification).

**Independent Test**: quickstart.md step 1 — unset each required field in turn and confirm `Settings()` construction raises identifying that exact field.

### Tests for User Story 1

- [X] T017 [P] [US1] New `tests/core/test_config.py`: for each group (`chat_model`, `embeddings`, `own_db`, `backend_db`, `storage`, `mineru`, `langfuse`, `logging`) and `ai_service_token`, add a test constructing `Settings`/the group directly with a required field missing or placeholder, asserting `ValidationError` naming that field, per spec FR-003 (test each independently — no module reload, no mutation of the process-wide `settings` singleton)
- [X] T018 [P] [US1] In the same file, add one passing-case test per group confirming a fully-valid construction raises nothing

### Implementation for User Story 1

- [X] T019 [US1] In `app/core/config.py`, remove `own_db`'s fake defaults (`postgres_db: "appdb"`, `postgres_user: "appuser"`, `postgres_password: "apppass"` → all `""`) and add `OwnDbSettings.model_validator(mode="after")` requiring `postgres_db`/`postgres_user`/`postgres_password` non-empty (research.md §4)
- [X] T020 [US1] In `app/core/config.py`, add `BackendDbSettings.model_validator(mode="after")` requiring `host`/`name`/`user`/`password` non-empty (unconditional — research.md §6); change `backend_database_url`'s return type from `str | None` to `str` (no longer conditional)
- [X] T021 [US1] In `app/core/config.py`, replace the current top-level `if not settings.use_mock_llm and settings.openai_api_key == "__mock__": raise` / embeddings equivalent with a `Settings`-level `model_validator(mode="after")` (cross-group: `chat_model.use_mock` gates both `chat_model.openai_api_key` and `embeddings.api_key`), preserving today's exact conditions and error text
- [X] T022 [US1] In `app/core/config.py`, move the storage fail-fast check (`storage_s3_bucket`/`access_key`/`secret_key` non-empty) into `StorageSettings.model_validator(mode="after")`, preserving today's batched error message listing all missing fields together
- [X] T023 [US1] In `app/core/config.py`, move the MinerU fail-fast check (`api_url` required unless `use_mock`) into `MinerUSettings.model_validator(mode="after")`, preserving today's error text
- [X] T024 [US1] In `app/core/config.py`, move the Langfuse fail-fast check (`host`/`public_key`/`secret_key` required when `enabled`) into `LangfuseSettings.model_validator(mode="after")`, preserving today's batched error message
- [X] T025 [US1] In `app/core/config.py`, move the `log_level` validity check (must be one of the fixed severity set) into `LoggingSettings.model_validator(mode="after")`
- [X] T026 [US1] In `app/core/config.py`, move the `ai_service_token` required check into a `Settings.model_validator(mode="after")` (stays flat, per data-model.md's "Ungrouped: Auth")
- [X] T027 [US1] In `app/backend_db/__init__.py::_ensure_engine()`, remove the `if url is None: raise RuntimeError("Backend database is not configured...")` branch — `backend_database_url` is now guaranteed set by the time any code runs (T020)
- [X] T028 [US1] In `tests/conftest.py`, add fabricated placeholder values for the now-required backend-DB fields (`BACKEND_DB__HOST`, `BACKEND_DB__NAME`, `BACKEND_DB__USER`, `BACKEND_DB__PASSWORD`), mirroring the existing `STORAGE_S3_*`/`MINERU__USE_MOCK` fabrication pattern already there

**Checkpoint**: quickstart.md step 1 passes for every required group, including the two that didn't fail fast before (`own_db`, `backend_db`). User Story 1 is independently functional and testable.

---

## Phase 4: User Story 2 - One source of truth for configuration values (Priority: P1) 🎯 MVP

**Goal**: The environment file is the only place that sets `ai-service`'s own configuration for normal operation; compose no longer declares a parallel, potentially-conflicting default; deterministic test-isolation overrides (`docker-compose.prod.yml`) still work.

**Independent Test**: quickstart.md steps 2–4 — set a non-default value in `.env`, confirm it takes effect with no compose-level override in the way; confirm `make prod-up` still boots deterministically off `.env` alone, since `docker-compose.prod.yml` pins no `environment:` block of its own.

### Implementation for User Story 2

- [X] T029 [US2] In `compose/docker-compose.yml`, delete the `ai-service` service's entire `environment:` block (all `OPENAI_BASE_URL`/`MODEL_NAME`/`USE_MOCK_LLM`/`POSTGRES_*`/`BACKEND_DB_*` — already renamed as of T013, but by this point the whole block is removed, not just renamed), leaving only `build: ..` and `env_file: ../.env`
- [X] T030 [US2] In `compose/docker-compose.yml`, remove the orphaned Langfuse comment block (originally explaining the `LANGFUSE_*` lines removed in an earlier change) that now sits above the `own_db`-equivalent lines with no matching content
- [X] T031 [US2] Run `make prod-build && make prod-up` (or `docker compose -f compose/docker-compose.yml -f compose/docker-compose.prod.yml up --build -d`, requires the external `nbe-prod` network — see `compose/docker-compose.prod.yml`'s header) and confirm it boots successfully sourced only from `.env` via the base file's `env_file:` — `docker-compose.prod.yml` pins no `environment:` block of its own, so the prod overlay has no second source of configuration either; `make prod-down` to stop

**Checkpoint**: quickstart.md steps 2–4 pass. User Stories 1 AND 2 both work independently.

---

## Phase 5: User Story 3 - Credentials never leak in plaintext (Priority: P2)

**Goal**: Every credential-shaped field is `SecretStr`; every call site that needs the real value explicitly opts in via `.get_secret_value()`, so a `repr()`/log/error message never exposes one in plaintext.

**Independent Test**: quickstart.md step 5 — trigger a validation failure and a normal debug print; confirm no credential value renders in plaintext in either.

### Implementation for User Story 3

- [X] T032 [US3] In `app/core/config.py`, type `chat_model.openai_api_key`, `embeddings.api_key`, `own_db.postgres_password`, `backend_db.password`, `storage.s3_access_key`, `storage.s3_secret_key`, `mineru.api_key`, `langfuse.secret_key`, and the flat `ai_service_token` as `pydantic.SecretStr`; update `own_database_url`/`backend_database_url` properties to call `.get_secret_value()` on the password field when building the connection string
- [X] T033 [P] [US3] In `app/core/llm.py`, drop the now-redundant `SecretStr(settings.chat_model.openai_api_key)` rewrap — pass `settings.chat_model.openai_api_key` directly to `ChatOpenAI(api_key=...)`
- [X] T034 [P] [US3] In `app/core/embedding.py`, same simplification for `settings.embeddings.api_key`
- [X] T035 [P] [US3] In `app/core/observability.py`, update the OTLP Basic Auth header build (`f"{...}:{settings.langfuse.secret_key}".encode()`) to call `settings.langfuse.secret_key.get_secret_value()` — masked-placeholder-in-header would otherwise break auth silently (research.md §5)
- [X] T036 [P] [US3] In `app/core/storage.py`, update `aws_access_key_id`/`aws_secret_access_key` to call `.get_secret_value()` on `settings.storage.s3_access_key`/`s3_secret_key`
- [X] T037 [P] [US3] In `app/core/security.py`, update the bearer token comparison to `credentials.credentials != settings.ai_service_token.get_secret_value()`
- [X] T038 [P] [US3] In `app/features/chat/checkpointer.py`, update `_psycopg_conn_string()` to call `settings.own_db.postgres_password.get_secret_value()` instead of `str(settings.postgres_password)` — the current `str(...)` coercion is exactly the silent-masking risk research.md §5 flags
- [X] T039 [P] [US3] In `app/features/ingestion/mineru_client.py`, update the `X-Api-Key` header build to call `settings.mineru.api_key.get_secret_value()`
- [X] T040 [US3] Grep the codebase for any remaining bare interpolation of a field renamed in T032 (`str(settings...)`, an f-string referencing one directly) to confirm no consuming call site was missed beyond T033–T039's list

**Checkpoint**: quickstart.md step 5 passes — no credential value appears in plaintext in a triggered validation failure or a normal `print(settings)`.

---

## Phase 6: User Story 4 - Complete, trustworthy environment template (Priority: P3)

**Goal**: `.env.example` (both repos) lists every variable actually required to run the service, with nothing missing and nothing stale.

**Independent Test**: quickstart.md step 6 — diff `.env.example` against `Settings`' actual field set; zero gaps either direction.

### Implementation for User Story 4

- [X] T041 [US4] Reconcile `.env.example` against the final field set from T032: add the previously-missing `BACKEND_DB__NAME` (present in the real `.env` today, absent from the template — spec.md Assumptions), confirm every other required field per contracts/env-var-contract.md §2 is present, remove anything stale
- [X] T042 [P] [US4] Reconcile `deploy/.env.example` similarly for any ai-service-facing vars it documents
- [X] T043 [US4] Run quickstart.md step 6's diff check (or an equivalent one-off script) confirming zero gaps between `.env.example` and `Settings`' required/optional field set in either direction

**Checkpoint**: quickstart.md step 6 passes. All four user stories are independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final quality gates spanning all stories.

- [X] T044 [P] Run `uv run ruff check .`, `uv run black --check .`, and `uv run mypy app` across all files touched in this feature
- [X] T045 [P] Run `uv run pytest tests -q --ignore=tests/integration` and `uv run pytest tests/integration -q` to confirm no regression from the full set of changes
- [X] T046 Run quickstart.md end-to-end (all 7 steps, including step 7's cross-repo deploy build) as final validation
- [X] T047 Review Constitution Principle II/VII's wording in `.specify/memory/constitution.md` against the behavior actually implemented by this feature; file a follow-up constitution amendment only if a real discrepancy is found (none is expected, since this feature implements what those principles already require rather than changing them)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories — none of them can be implemented or tested against old field names.
- **User Stories (Phase 3–6)**: All depend on Foundational completion (T016 checkpoint).
  - US1 and US2 (both P1) have no dependency on each other — safe to run in parallel or in either order.
  - US3 (P2) depends on US1 having established the group structure (Phase 2) but not on US1's validators or US2's compose changes — could run in parallel with either, though sequencing after US1/US2 is simpler to review.
  - US4 (P3) depends on T032 (US3's `SecretStr` typing) only insofar as the final field set must be stable before reconciling the template — practically, do US4 last.
- **Polish (Phase 7)**: Depends on all four user stories being complete.

### User Story Dependencies

- **US1 (P1)**: Foundational only. Independently testable via quickstart step 1.
- **US2 (P1)**: Foundational only. Independently testable via quickstart steps 2–4. No dependency on US1.
- **US3 (P2)**: Foundational only (structurally); best done after US1 so the validators T033–T039 touch are final, but does not require US1's validators to exist to type fields as `SecretStr`.
- **US4 (P3)**: Foundational + benefits from US1 (final required-field list) and US3 (final field set including renamed `SecretStr` fields) being done first, to avoid reconciling the template twice.

### Within Each User Story

- Tests before implementation where tests are included (US1 only, per FR-003's explicit testability requirement — the other three stories are compose/call-site/documentation changes without new pure-logic branches worth unit-testing in isolation).
- Story complete before moving to next priority, or run US1 → US2 in parallel (both P1) → US3 → US4 sequentially if working solo.

### Parallel Opportunities

- T004–T011 (Foundational per-group call-site renames) — all touch disjoint file sets, safe to run in parallel.
- T017–T018 (US1 tests) — same new file, sequential in practice despite `[P]` marking on different test functions; treat as one sitting.
- T033–T039 (US3 per-file `.get_secret_value()` updates) — all disjoint files, safe to run in parallel.
- US1 and US2 as whole phases can be staffed in parallel (both P1, no shared files: US1 touches `app/core/config.py` + `app/backend_db/__init__.py` + `tests/`; US2 touches only `compose/*.yml`).

---

## Parallel Example: Foundational Phase

```bash
# After T002/T003 (config.py restructure) land, launch all group call-site renames together:
Task: "Update chat_model group call sites (T004)"
Task: "Update embeddings group call sites (T005)"
Task: "Update own_db group call sites (T006)"
Task: "Update backend_db group call site (T007)"
Task: "Update storage group call sites (T008)"
Task: "Update mineru group call sites (T009)"
Task: "Update langfuse group call site (T010)"
Task: "Update logging group call site (T011)"
```

## Parallel Example: User Story 3

```bash
Task: "Update app/core/llm.py (T033)"
Task: "Update app/core/embedding.py (T034)"
Task: "Update app/core/observability.py (T035)"
Task: "Update app/core/storage.py (T036)"
Task: "Update app/core/security.py (T037)"
Task: "Update app/features/chat/checkpointer.py (T038)"
Task: "Update app/features/ingestion/mineru_client.py (T039)"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 — both P1)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks everything, and is the largest single phase by file count).
3. Complete Phase 3 (US1) and Phase 4 (US2) — independent of each other, deliverable together as the MVP: every required group fails fast, and there's exactly one place to configure each value.
4. **STOP and VALIDATE**: run quickstart.md steps 1–4.

### Incremental Delivery

1. Setup + Foundational → foundation ready (largest, riskiest phase — full rename across ~20 files in two repos).
2. Add US1 → validate independently (quickstart step 1) → the core reliability property lands.
3. Add US2 → validate independently (quickstart steps 2–4) → the core consistency property lands.
4. Add US3 → validate independently (quickstart step 5) → credential hygiene lands.
5. Add US4 → validate independently (quickstart step 6) → template completeness lands.
6. Polish (Phase 7) → full-suite validation, including the cross-repo build (quickstart step 7).

---

## Notes

- [P] tasks touch different files with no dependency on an incomplete task in the same phase.
- The Foundational phase is unusually large for this feature because the rename spans ~20 call sites across the codebase (research.md's plan.md Project Structure under-listed this — only the `SecretStr`-relevant subset — the full list was enumerated during task generation by grepping every `settings.*` usage) plus two compose files in a second repository.
- Commit after each phase checkpoint, not necessarily after each task — T004–T011 in particular are natural to land as one commit given how tightly coupled they are to T002.
- Avoid: reintroducing a flat/grouped dual-read fallback for old env var names (explicitly rejected in research.md §7) — if a rename is missed, fix the call site, don't add a compatibility shim.
