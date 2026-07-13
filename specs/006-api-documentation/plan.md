# Implementation Plan: API Documentation

**Branch**: `006-api-documentation` | **Date**: 2026-07-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/006-api-documentation/spec.md`

## Summary

Enrich the service's existing auto-generated OpenAPI documentation (Swagger UI at `/docs`,
ReDoc at `/redoc`, raw schema at `/openapi.json`) so every `/internal/*` endpoint carries a
purpose description, a fully-typed response model (including error responses), and at least
one example request/response — all derived from the same Pydantic request/response models the
API already uses to validate and serialize traffic, so nothing drifts out of sync by
construction. This feature does not change who can reach the docs or the API — `/docs`,
`/redoc`, `/openapi.json`, and every `/internal/*` endpoint's authentication posture stay
exactly as they are today. No new authentication mechanism, no new dependencies, no new own-DB
tables, no new routes — this is purely additive metadata on existing routers and schemas.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI ≥0.115 (native OpenAPI/Swagger UI/ReDoc generation), Pydantic v2 (`Field(description=..., examples=...)`, `model_config = ConfigDict(json_schema_extra=...)`)

**Storage**: N/A — this feature adds no persisted data; own DB and backend DB are unaffected

**Testing**: No new test infrastructure — existing `tests/features/test_auth_matrix.py` and per-feature router tests already exercise these endpoints and are unaffected by adding descriptions/examples/response models

**Target Platform**: Linux container (unchanged — same FastAPI app, no infra change)

**Project Type**: Web service (single FastAPI app, feature-bounded vertical slices per Constitution V)

**Performance Goals**: N/A — documentation generation is build/import-time schema assembly, not a hot request path; no throughput target applies

**Constraints**: Must not change the existing auth behavior of any `/internal/*` endpoint or of `/docs`/`/redoc`/`/openapi.json` — this feature only adds descriptive metadata to routes and schemas that already exist

**Scale/Scope**: 9 `/internal/*` endpoints across 5 feature slices (chat, analytics ×3, plan ×2, ingestion ×2, recommendations ×1) plus 2 public probes (`/health`, `/ready`) — see Data Model for the exact endpoint inventory

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applies? | Check |
|---|---|---|
| I. Mandatory Automated Testing | Yes | No new runtime behavior is introduced, so no new test infrastructure is required; the full existing suite (including `test_auth_matrix.py`) must keep passing unchanged. **PASS** |
| II. Security & Secrets Discipline | Yes | This feature makes no change to authentication: every `/internal/*` route keeps requiring `require_token` exactly as before, and `/docs`/`/redoc`/`/openapi.json` keep their existing (unauthenticated) access posture. **PASS** |
| III. Data Protection & Compliance | Yes | Example request/response payloads shown in docs MUST use synthetic, non-PII placeholder values — never real customer data — consistent with the prompt/log minimization rule. **PASS**, enforced by design (examples are authored literals, not derived from real records) |
| IV. Data Ownership & Access Boundaries | No | No new tables, no new backend-DB access | N/A |
| V. Feature-Bounded Modular Architecture | Yes | Enrichment lives entirely inside each owning feature slice's existing `router.py`/`schemas.py`; no new cross-cutting module is introduced. **PASS** |
| VI. LLM & Agent Architecture | No | No agent/LLM behavior changes | N/A |
| VII. Operational Readiness & Fail-Fast Configuration | Yes | `/health` and `/ready` remain dependency-free and unchanged. No config changes, so nothing new to fail-fast validate. **PASS** |
| VIII. Library-First, Minimal Implementation | Yes | Uses FastAPI's native OpenAPI generation (`response_model`, `responses=`, `Field(description=, examples=)`) rather than hand-rolling a docs renderer or a parallel schema format. **PASS** |

No violations requiring justification — Complexity Tracking is not needed.

**Post-Phase-1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) confirm
this stays additive metadata only — no new routes, no new auth path, no new dependency. Gate
re-confirmed: **PASS**, no violations.

## Project Structure

### Documentation (this feature)

```text
specs/006-api-documentation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
app/
├── core/
│   └── security.py          # add a shared ERROR_RESPONSES dict (401/422), reused across routers
├── features/
│   ├── chat/
│   │   ├── router.py          # add description, responses={...} for the SSE endpoint
│   │   └── schemas.py         # add Field(description=, examples=) to ChatTurnRequest
│   ├── analytics/
│   │   ├── router.py          # add response_model to post-ingestion/monthly-summary/anomaly-check
│   │   └── schemas.py         # add Field(description=, examples=) to request/result models,
│   │                          #      plus a new PostIngestionResult model
│   ├── plan/
│   │   ├── router.py          # add descriptions, responses={...}
│   │   └── schemas.py         # add Field(description=, examples=), plus a new NextQuestionResponse
│   ├── ingestion/
│   │   ├── router.py          # already has response_model + docstrings; add responses={...}
│   │   └── schemas.py         # add Field(description=, examples=)
│   └── recommendations/
│       ├── router.py          # add description, responses={...}
│       └── schemas.py         # add Field(description=, examples=)
```

**Structure Decision**: No new feature slice and no new cross-cutting module. This is
enrichment work distributed across the 5 existing feature slices (each owns its own
router/schemas, per Constitution V), plus one shared constant in the existing
`app/core/security.py`.

## Complexity Tracking

*No Constitution Check violations — this section is not needed.*
