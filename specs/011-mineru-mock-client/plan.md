# Implementation Plan: Mock MinerU Client for Offline Ingestion

**Branch**: `011-mineru-mock-client` | **Date**: 2026-07-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-mineru-mock-client/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

`settings.use_mock_mineru` already exists and is already validated at startup, but
`get_mineru_client()` in `app/features/ingestion/mineru_client.py` always returns
`HttpMineruClient` regardless of the flag, so `USE_MOCK_MINERU=1` currently does
nothing — ingestion still requires a reachable MinerU instance. This plan adds
`MockMineruClient` (a second, plain `MineruClient` Protocol implementation returning a
fixed, deterministic `ParsedDocument` — no network call, no failure simulation, no
input inspection) and updates `get_mineru_client()` to select it when
`settings.use_mock_mineru` is true, mirroring the already-shipped
`MockNormalizerClient` / `get_normalizer_client()` pattern exactly. See research.md for
the resolved design decisions and spec.md's Clarifications for the locked-in content
shape.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, Pydantic v2 / pydantic-settings (existing project
stack — no new dependency introduced; the mock reuses the existing `MineruClient`
Protocol and `ParsedDocument` dataclass as-is)

**Storage**: N/A — no schema, migration, or persisted-entity change (see data-model.md)

**Testing**: pytest / pytest-asyncio (existing project stack; new tests mirror the
factory-selection pattern in `tests/features/ingestion/test_normalizer.py:357-372`)

**Target Platform**: Linux server (containerized FastAPI service)

**Project Type**: Single project — FastAPI backend, feature-bounded vertical slices
(constitution Principle V); this change is entirely within the existing `ingestion`
slice

**Performance Goals**: N/A — the mock is an in-memory, no-I/O return with no
performance target beyond "no network call"

**Constraints**: No network calls in mock mode; deterministic, fixed output regardless
of input; no new required configuration (FR-005); no change to existing startup
validation behavior when mock mode is disabled (FR-007)

**Scale/Scope**: One new class (`MockMineruClient`) plus a one-line branch update in an
existing factory function (`get_mineru_client()`), plus accompanying unit tests — no DB,
API contract, or cross-slice changes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|---|---|
| I. Mandatory Automated Testing | PASS — new tests are added (factory-selection + fixed-output assertions, mirroring an existing pattern), fully deterministic, no external-network call in any test path. |
| II. Security & Secrets Discipline | N/A — no new endpoint, no new secret; existing token-gated `/internal/ingestion/*` routes are unchanged. |
| III. Data Protection & Compliance | PASS — mock output is synthetic, clearly-fake placeholder data (no real PII), never derived from real statement content. |
| IV. Data Ownership & Access Boundaries | N/A — no database read or write path introduced. |
| V. Feature-Bounded Modular Architecture | PASS — entire change stays within `app/features/ingestion/` (and its tests); no cross-slice reach-in. |
| VI. LLM & Agent Architecture | N/A — this is the document-parsing (MinerU) client, not the LLM/agent layer. |
| VII. Operational Readiness & Fail-Fast Configuration | PASS — existing startup validation for `use_mock_mineru`/`mineru_api_url` (`app/core/config.py:151-155`) is unchanged (FR-007); no new required config (FR-005). |
| VIII. Library-First, Minimal Implementation | PASS — this is the explicit driver of the design: reuse the already-shipped swappable-client shape (`Protocol` + factory branch) rather than inventing a parallel mechanism; no speculative abstraction added. |

No violations. Complexity Tracking is not applicable.

## Project Structure

### Documentation (this feature)

```text
specs/011-mineru-mock-client/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── checklists/
│   └── requirements.md  # Spec quality checklist (/speckit.specify command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

No `contracts/` directory — see research.md §5 (no new externally-exposed interface).

### Source Code (repository root)

Single-project FastAPI service, organized as feature-bounded vertical slices
(constitution Principle V). This change is entirely within the existing `ingestion`
slice — no new files, folders, or slices are created.

```text
app/features/ingestion/
├── mineru_client.py          # MODIFIED: add MockMineruClient; update get_mineru_client()
│                              #   to branch on settings.use_mock_mineru
├── normalizer/
│   ├── mock.py                # unchanged — pattern reference (MockNormalizerClient)
│   └── __init__.py             # unchanged — pattern reference (get_normalizer_client())
└── service/
    └── process.py             # unchanged — consumes get_mineru_client() as-is

app/core/config.py              # unchanged — settings.use_mock_mineru and its startup
                                 #   validation already exist and are correct

tests/features/ingestion/
├── test_mineru_client.py      # MODIFIED: add factory-selection tests + MockMineruClient
│                              #   fixed-output tests
├── test_normalizer.py          # unchanged — pattern reference for factory-selection tests
└── test_service.py             # unchanged — existing _FakeMineruClient-injected tests
                                 #   remain the error-path/fixture-driven seam
```

**Structure Decision**: Single FastAPI project, vertical-slice architecture already in
place. All changes land inside the existing `app/features/ingestion/` slice and its
`tests/features/ingestion/` counterpart — no new top-level directories, no new slice,
no changes outside this feature's existing footprint.

## Complexity Tracking

*No Constitution Check violations — this section is not applicable.*
