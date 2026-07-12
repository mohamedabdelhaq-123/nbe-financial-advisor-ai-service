# Implementation Plan: Object Storage Infrastructure

**Branch**: `003-object-storage` | **Date**: 2026-07-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-object-storage/spec.md`

## Summary

Add a single cross-cutting core module, `app/core/storage.py`, giving any
part of the service (routers, background jobs, agent/graph nodes) a way to
write, read, check existence of, delete, and list binary blobs against an
S3-compatible object store (SeaweedFS in this deployment, but the design
targets any S3-compatible endpoint). The module is `aioboto3`-based, exposes
a plain callable factory (`get_storage_backend()`) mirroring the existing
`get_chat_model()` pattern rather than a FastAPI `Depends`, and does not
provision, run, or manage the SeaweedFS instance itself — only the config
surface to point at wherever it's already running. No HTTP routes are
added; this is internal infrastructure consumed in-process.

## Technical Context

**Language/Version**: Python 3.12 (existing project baseline)

**Primary Dependencies**: FastAPI, pydantic-settings (existing); `aioboto3`
(new — async S3-compatible client backed by `aiobotocore`/`botocore`)

**Storage**: S3-compatible object storage (SeaweedFS's S3 gateway in this
deployment) — blobs addressed by logical key within one configured bucket.
No relational schema is introduced by this feature; the service's own
Postgres DB is unaffected.

**Testing**: `pytest` / `pytest-asyncio` (existing). A deterministic,
network-free unit test for key-traversal validation always runs; an
S3-compatible round-trip integration test follows the same
optional-when-configured pattern already used for `backend_db_host` (skips
cleanly unless real endpoint/bucket/credentials are supplied via
environment).

**Target Platform**: Linux container (existing service deployment
target); no new deployment artifact — the object store itself is external,
pre-existing shared infrastructure this feature does not provision.

**Project Type**: Single-project web service (existing FastAPI app,
feature-sliced architecture) — this feature adds one cross-cutting core
module, no new project/package.

**Performance Goals**: No new performance target beyond the existing
service's async-non-blocking expectations; blob operations must not block
the event loop (aioboto3 is natively async, so this holds by construction).

**Constraints**:
- No HTTP endpoints exposed for upload/download (internal-only, FR-011).
- Must be usable without an active HTTP request context (FR-010) — rules
  out designs that depend on FastAPI's request-scoped `Depends` lifecycle.
- Must not auto-create the target bucket (FR-009) — least-privilege,
  consistent with the read-only-role precedent already set for the backend
  DB (Constitution Principle IV).
- Must fail fast at startup on incomplete storage credentials (FR-008),
  not at first use.
- Must reject path-traversal-capable keys before any network call
  (FR-007).

**Scale/Scope**: One new core module (`app/core/storage.py`), one new
`Settings` block, one new runtime dependency, two new test files. No
existing feature slice is modified by this feature itself (adoption by
chat/analytics/etc. is future, out-of-scope work building on top of this).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Mandatory Automated Testing** — PASS. Unit test (key-traversal) is
  deterministic and network-free. The S3-compatible integration test
  mirrors the already-established `backend_db_host`-empty-skips pattern
  (Constitution: "read-only access to backend tables MUST be exercised
  through fixtures or mocks, never a live backend" — analogously, this
  feature's live-object-store test is opt-in via config, never required
  for CI to stay green offline).
- **II. Security & Secrets Discipline** — PASS. Storage credentials live
  only in `Settings`/environment, never committed; `.env.example` ships
  placeholder/blank values; startup fails immediately if required
  credentials are incomplete (FR-008), mirroring the existing
  `openai_api_key`/`ai_service_token` fail-fast checks.
- **III. Data Protection & Compliance** — PASS, with a scope note: this
  module is a generic byte-addressable blob store with no visibility into
  what a caller stores. It cannot itself perform PII minimization or
  redaction on opaque bytes — that responsibility sits with whichever
  feature decides what to store (same division of responsibility as
  `get_own_session()` not inspecting the queries run against it). Any
  feature that stores backend-derived data through this module remains
  bound by Principle III's egress-minimization requirement at the point it
  decides what to write. Audit logging of *privileged* storage actions
  (e.g. "user downloaded their own statement") is likewise the calling
  feature's responsibility, since only the feature layer knows whether a
  given read/write is privileged — this module logs no business-level
  audit events itself, the same way the DB session factory doesn't.
- **IV. Data Ownership & Access Boundaries** — N/A (no database access
  introduced). The bucket-not-auto-provisioned rule (FR-009) mirrors this
  principle's least-privilege spirit even though it isn't a DB boundary.
- **V. Feature-Bounded Modular Architecture** — PASS. `storage.py` lives in
  `app/core/` alongside `config.py`/`db.py`/`llm.py` as cross-cutting infra
  used by feature slices, not as a new package-by-layer top-level folder.
- **VI. LLM & Agent Architecture** — N/A directly; noted as a future
  consumer (agent/graph nodes may persist generated artifacts through this
  module), which is why FR-010 requires it work outside an HTTP request
  context.
- **VII. Operational Readiness & Fail-Fast Configuration** — PASS. Storage
  settings validate at import time (FR-008) with no live connection
  attempt at startup (stays offline, consistent with `backend_db_host`
  being allowed blank without a startup network probe).

No violations — Complexity Tracking table is not needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-object-storage/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   └── storage-module-interface.md
└── tasks.md              # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

Existing feature-sliced FastAPI service (Constitution Principle V) — no new
top-level structure. This feature only touches cross-cutting core infra and
tests:

```text
app/
├── core/
│   ├── config.py         # MODIFIED: add storage_s3_* Settings + fail-fast check
│   ├── storage.py         # NEW: get_storage_backend(), validate_storage_key()
│   ├── db.py              # unchanged — pattern referenced (eager singleton + fresh-resource factory)
│   └── llm.py             # unchanged — pattern referenced (plain callable factory)
└── features/
    └── ...                # unchanged by this feature; future consumers

tests/
├── core/
│   └── test_storage.py    # NEW: key-traversal unit test
├── integration/
│   └── test_storage_s3.py # NEW: real-SeaweedFS round-trip, skipped when unconfigured
└── conftest.py             # MODIFIED: add real_s3_storage_env skip-when-unconfigured fixture

.env.example                # MODIFIED: add storage_s3_* example vars
pyproject.toml               # MODIFIED: add aioboto3 runtime dependency
```

**Structure Decision**: Single existing project, feature-sliced
architecture (Constitution Principle V). This feature adds one new
cross-cutting core module (`app/core/storage.py`) alongside the existing
`config.py`/`db.py`/`llm.py`, plus corresponding tests — no new
project/package, no new top-level directories, no HTTP routes.

## Complexity Tracking

*Not applicable — Constitution Check has no violations to justify.*
