# Implementation Plan: Consistent, Fault-Tolerant Environment Configuration

**Branch**: `014-env-config-consistency` | **Date**: 2026-07-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/014-env-config-consistency/spec.md`

## Summary

Make the ai-service's own runtime configuration have exactly one authoritative source (the environment file, via `env_file`) instead of two potentially-conflicting ones (compose `environment:` defaults plus the environment file), reorganize `app/core/config.py`'s flat `Settings` class into named, per-domain groups with per-group fail-fast validation (closing the gap where the service's own database credentials, unlike every other credential group, have no "missing/placeholder" check), extend that same fail-fast treatment to backend database access (now unconditionally required), mask every credential-shaped field from plaintext exposure via `pydantic.SecretStr`, and keep both this repo's `.env.example` and the real production deploy repo's compose file in sync with the resulting env var names.

## Technical Context

**Language/Version**: Python 3.12 (existing service)

**Primary Dependencies**: `pydantic` / `pydantic-settings` (existing, no version change) — nested `BaseModel` groups under the existing `Settings(BaseSettings)`, `env_nested_delimiter="__"`, `@model_validator(mode="after")` for cross-field fail-fast checks, `SecretStr` for credential fields. No new package dependencies.

**Storage**: N/A — no schema, table, or migration changes. The service's own database and the backend's read-only database are both touched only as *configuration* (credentials/connection settings), not as data models.

**Testing**: `pytest` (existing suite). New/changed unit tests cover each configuration group's fail-fast validator (missing value, placeholder value, valid value) in isolation via direct `Settings(...)`/group construction — no module reload, no mutation of the process-wide `settings` singleton, per spec FR-003. `tests/conftest.py` gains fabricated placeholder values for the now-required backend-database fields, mirroring its existing `STORAGE_S3_*`/`USE_MOCK_MINERU` pattern (spec Assumptions).

**Target Platform**: Linux containers via Docker Compose — this repo's local/CI compose files (`compose/docker-compose.yml`, `.dev.yml`, `.prod.yml`) and the real production deploy repo (`nbe-financial-advisor-backend/deploy/docker-compose.yml`), which builds this service from source and wires its own environment directly (no `env_file`, all literal `environment:` entries).

**Project Type**: Existing single-project FastAPI service; this feature touches its central `app/core/config.py` module, every call site that reads a credential field, and compose/deploy files in two repos — no new project/package boundary.

**Performance Goals**: N/A — configuration is read once at process startup; no request-path impact.

**Constraints**: Every required configuration group MUST fail startup immediately and identifiably when unset/placeholder (spec FR-002, Constitution Principle VII). No credential value may render in plaintext via `str()`/`repr()`/an f-string built carelessly around a `SecretStr` field — every call site that currently interpolates a credential into a connection string, header, or comparison MUST be updated to call `.get_secret_value()` explicitly, or it silently sends/compares the masked placeholder instead of the real secret (research.md §5). Renaming env vars is a two-repo change: this repo's `compose/*.yml`/`.env.example` AND `nbe-financial-advisor-backend/deploy/docker-compose.yml`/`.env.example` MUST move together, since the deploy repo hardcodes every current flat var name with no `env_file` fallback of its own.

**Scale/Scope**: One core module (`app/core/config.py`) reorganized into ~9 configuration groups; 4 compose/env-template files across two repos; ~20 call sites updated for renamed field access (research.md's Foundational rename, tasks.md T004–T011), of which ~8 are also updated for `SecretStr`/`.get_secret_value()` (research.md §5, tasks.md T032–T039); `tests/conftest.py` and the config unit-test suite.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design below.*

| Principle | Assessment |
|---|---|
| I. Mandatory Automated Testing | **PASS.** New/changed tests exercise validators via direct `Settings`/group construction — in-process, no real DB/network call. Backend-DB tests already bypass config entirely via `monkeypatch.setattr(get_backend_session, ...)` (unaffected). Fabricated placeholder creds for the now-required backend-DB fields follow the existing `STORAGE_S3_*` pattern in `conftest.py`, not a real backend connection. |
| II. Security & Secrets Discipline | **PASS, and this feature directly strengthens it.** "Configuration MUST fail fast at startup when a required secret is missing or set to a placeholder value" is the principle this feature closes the last gap on (own-DB credentials). `SecretStr` adoption is new, additive hardening beyond what the principle already requires. |
| III. Data Protection & Compliance (NON-NEGOTIABLE) | **PASS / not applicable.** No PII/financial data handling changes; this is infrastructure credential hygiene, a different concern from Principle III's prompt/telemetry minimization scope. |
| IV. Data Ownership & Access Boundaries | **PASS.** Backend DB access becomes unconditionally required rather than optional, but the read-only role/boundary enforcement itself (dedicated `ai_readonly` role, excluded `Base`) is unchanged — this feature only changes *whether missing backend-DB config is caught at startup vs. deferred*, not what the service is allowed to do with that connection. |
| V. Feature-Bounded Modular Architecture | **PASS.** `app/core/config.py` is existing cross-cutting core infrastructure (same placement precedent as `app/core/logging.py`/`observability.py`); no feature-slice boundary is crossed. |
| VI. LLM & Agent Architecture | **PASS / not applicable.** `openai_base_url`/`model_name` stay config-driven and swappable, unchanged in behavior — only their env var name and grouping change. |
| VII. Operational Readiness & Fail-Fast Configuration | **PASS, and this is the core of the feature.** Extends "raise immediately on invalid or incomplete settings" to the two groups that previously didn't have it (own DB, backend DB), and moves the mechanism from ad hoc top-level `if`/`RuntimeError` blocks tied to a singleton to per-group validators, satisfying the same principle more testably. |
| VIII. Library-First, Minimal Implementation | **PASS.** Uses `pydantic`/`pydantic-settings` native mechanisms throughout (`BaseModel` nesting, `env_nested_delimiter`, `model_validator`, `SecretStr`) — no hand-rolled validation framework. Single-field settings (`ai_service_token`) are deliberately left ungrouped rather than wrapped in a one-field group, avoiding speculative structure ahead of need. |

No violations requiring justification in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/014-env-config-consistency/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/            # Phase 1 output
└── tasks.md              # Phase 2 output (/speckit.tasks command — not created by this command)
```

### Source Code (repository root, this repo)

```text
app/
├── core/
│   ├── config.py                 # edited: Settings reorganized into nested BaseModel groups
│   │                              #         (chat_model, embeddings, own_db, backend_db, storage,
│   │                              #         mineru, langfuse, logging) + ai_service_token flat;
│   │                              #         model_validator(mode="after") per group; SecretStr
│   │                              #         on every credential field; own_database_url /
│   │                              #         backend_database_url updated for new field paths
│   │                              #         and .get_secret_value()
│   ├── llm.py                    # edited: settings.openai_api_key is already a SecretStr —
│   │                              #         drop the now-redundant SecretStr(...) rewrap
│   ├── embedding.py               # edited: same as llm.py, for embedding_api_key
│   ├── observability.py           # edited: Basic Auth header build uses
│   │                              #         langfuse_secret_key.get_secret_value()
│   ├── storage.py                 # edited: aws_secret_access_key uses .get_secret_value()
│   ├── security.py                # edited: ai_service_token comparison uses .get_secret_value()
│   ├── system.py                  # edited: mineru group field paths renamed (no SecretStr)
│   └── db.py                      # edited: own_database_url call shape unchanged, field paths renamed
├── backend_db/
│   └── __init__.py                # edited: backend_database_url is no longer Optional;
│                                   #         _ensure_engine()'s "not configured" branch removed
│                                   #         (startup-time validation now guarantees it's set)
└── features/
    ├── chat/checkpointer.py       # edited: postgres_password uses .get_secret_value()
    ├── ingestion/mineru_client.py # edited: mineru_api_key uses .get_secret_value()
    ├── recommendations/seed.py    # edited: own_database_url field paths renamed (no SecretStr)
    ├── embed/router.py            # edited: embeddings group field paths renamed
    ├── ingestion/service/process.py, service/normalize.py  # edited: storage group field paths renamed
    ├── chat/agents/analysis.py, agents/maestro.py, graph.py, service.py, summarize.py  # edited:
    │                              #         chat_model group field paths renamed (use_mock_llm →
    │                              #         chat_model.use_mock)
    ├── ingestion/normalizer/__init__.py, normalizer/graph.py, normalizer/mock.py  # edited:
    │                              #         chat_model group field paths renamed
    └── plan/service.py            # edited: chat_model group field paths renamed

# The SecretStr/.get_secret_value() ripple above is the ~8-file subset (research.md §5). The
# remainder of app/ listed here is the pure field-path rename (settings.<old> → settings.<group>.<field>)
# that Foundational task T004–T011 performs across ~20 files total — see tasks.md for the authoritative
# per-group file list; this tree mirrors it rather than restating a narrower ~8-file count.

tests/
├── conftest.py                    # edited: fabricated placeholder BACKEND_DB__* values,
│                                   #         same pattern as existing STORAGE_S3_*/MINERU__
└── core/
    └── test_config.py             # new/edited: per-group fail-fast validator tests

compose/
├── docker-compose.yml             # edited: ai-service's `environment:` block deleted entirely
│                                   #         (build: .. + env_file: ../.env only); orphaned
│                                   #         Langfuse comment removed
├── docker-compose.prod.yml        # edited: pinned override keys renamed to match new
│                                   #         grouped env var names (values/behavior unchanged)
├── langfuse/docker-compose.yml    # unchanged — has no env_file of its own, keeps
│                                   #             ${LANGFUSE_*:-default} but consumer-side
│                                   #             names on the ai-service side still rename
└── mineru/docker-compose.yml      # unchanged

.env.example                       # edited: renamed vars, BACKEND_DB__* now required
                                   #         (no longer optional), missing NAME var added
```

### Source Code (`nbe-financial-advisor-backend/deploy`, separate repo)

```text
deploy/
├── docker-compose.yml             # edited: ai-service's `environment:` block (no env_file
│                                   #         there today) renamed to match the new grouped
│                                   #         env var names — same values, same defaults,
│                                   #         only the keys change
└── .env.example                   # edited: any renamed vars referenced there updated to match
```

**Structure Decision**: Single existing project (FastAPI service); no new project/package boundary. The one structurally notable point is that this feature's blast radius spans two repositories, because the real production deploy compose file hardcodes the current flat env var names directly (confirmed by reading it — no `env_file` involved there) rather than sourcing them from this repo's `.env.example` convention. Renaming without updating that file would silently break production, so it is treated as in-scope, not a follow-up.

## Post-Design Constitution Check

*Re-checked after Phase 1 (data-model.md, contracts/, quickstart.md).*

No new violations introduced by the design artifacts. Confirms: the own-DB and backend-DB fail-fast gaps this feature closes are exactly the ones Principle VII already requires closed (data-model.md groups table); `SecretStr` adoption's call-site ripple is fully enumerated (research.md §5, Project Structure above) rather than partially done, so no credential field is left both "typed as secret" and "still interpolated as plaintext somewhere"; the cross-repo deploy-file update is captured as a first-class contract item (contracts/env-var-contract.md) rather than left implicit. Gate remains **PASS**.

## Complexity Tracking

*No Constitution Check violations — this section is not applicable.*
