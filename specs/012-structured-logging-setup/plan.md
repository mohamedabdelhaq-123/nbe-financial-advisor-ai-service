# Implementation Plan: Structured Logging Setup

**Branch**: `012-structured-logging-setup` | **Date**: 2026-07-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-structured-logging-setup/spec.md`

## Summary

Replace the service's ad hoc, per-file `logging.getLogger` usage with a
single, shared structured-logging setup: every log line is emitted as one
JSON object to stdout, carries a self-generated per-request/job correlation
identifier, and never contains PII, financial data, or secrets — except raw
LLM prompt/completion and DB query content, which is emitted only under an
explicit, default-off debug flag. Implemented as cross-cutting infrastructure
in `app/core/`, using `structlog` (wrapping stdlib `logging`) per the
constitution's library-first principle, with a FastAPI middleware for
correlation-ID binding and request/response access logging.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI (existing), `structlog` (new — structured
logging with stdlib-`logging` integration and contextvars-based binding for
correlation IDs)

**Storage**: N/A — log output goes to stdout only; no new database tables

**Testing**: pytest / pytest-asyncio (existing), asserting on captured stdout
log records via `structlog.testing.capture_logs` / `caplog`

**Target Platform**: Linux container (existing deployment target)

**Project Type**: Single backend service (existing FastAPI app) — this
feature adds cross-cutting infrastructure, not a new feature slice

**Performance Goals**: Logging overhead must stay negligible relative to
request handling (no synchronous I/O beyond a stdout write per line); no
specific throughput target beyond "does not become the bottleneck"

**Constraints**: Liveness/readiness probes must remain unblocked by logging
(Principle VII); log format must stay identical across environments (no
environment-conditional pretty-printing branch, per FR-001); default debug
verbosity must never emit raw prompt/query content (FR-011)

**Scale/Scope**: Applies service-wide — every feature slice under
`app/features/*` and cross-cutting code under `app/core/*`; no scope
reduction to a subset of slices

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Mandatory Automated Testing | New logging setup must ship with deterministic unit tests (format, correlation-ID propagation, redaction, debug-flag default) that don't depend on real timestamps or external services | PASS — tests are pure/deterministic, no live model/DB calls needed |
| II. Security & Secrets Discipline | Logs must never contain secrets (API keys, bearer token, DB credentials) at any verbosity | PASS — FR-005 makes this unconditional; enforced via redaction/allowlisted fields, not developer discipline alone |
| III. Data Protection & Compliance | PII/financial data must never leave via logs, mirroring the existing prompt/DTO minimization boundary | PASS — FR-005/FR-011 extend the same minimization guarantee to the logging egress point |
| IV. Data Ownership & Access Boundaries | Logging must not introduce any new backend-DB write path | PASS — feature is stdout-only, no DB writes, backend or own |
| V. Feature-Bounded Modular Architecture | Logging is cross-cutting infrastructure, not a vertical feature slice | PASS — lives in `app/core/`, alongside `config.py`, `db.py`, `security.py`, matching the existing pattern; feature slices only consume a shared `get_logger()`, never reimplement setup |
| VI. LLM & Agent Architecture | Debug-mode raw prompt/completion logging must not become a silent default or bypass PII-safe prompting elsewhere | PASS — FR-011 keeps it opt-in and off by default; does not change how prompts are constructed, only what may optionally be logged |
| VII. Operational Readiness & Fail-Fast Configuration | Log level config must be validated at startup; probes must stay unaffected | PASS — new `log_level`/debug settings follow the existing `Settings` fail-fast pattern in `app/core/config.py`; probes (`app/core/system.py`) make no logging-dependent calls |
| VIII. Library-First, Minimal Implementation | Prefer a maintained library over hand-rolled JSON formatting/context propagation | PASS — `structlog` is the established, well-maintained library for this; avoids hand-rolling a JSON `logging.Formatter` and a manual contextvar-to-`logging`-record bridge |

No violations requiring justification — Complexity Tracking is not needed.

## Project Structure

### Documentation (this feature)

```text
specs/012-structured-logging-setup/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

No `contracts/` directory: this feature introduces no new API/CLI/external
interface. Logging is internal observability infrastructure consumed via
stdout, not via a request/response or wire contract.

### Source Code (repository root)

```text
app/
├── core/
│   ├── config.py            # existing — extended with log_level / debug-content settings
│   ├── logging.py            # NEW — structlog configuration, get_logger(), correlation-id binding helpers
│   ├── request_logging.py    # NEW — FastAPI middleware: mint/bind correlation ID, log access line per request
│   ├── system.py             # existing — unaffected (probes stay logging-independent)
│   └── ...                   # existing: db.py, security.py, llm.py, storage.py, audit.py
├── features/
│   ├── chat/service.py        # existing ad hoc `logging.getLogger` usage migrated to app.core.logging.get_logger
│   ├── ingestion/normalizer/graph.py  # existing ad hoc usage migrated
│   └── .../                   # all other slices adopt the same get_logger() for any new logging
└── main.py                    # existing — wires the new middleware in create_app()

tests/
├── core/
│   └── test_logging.py        # NEW — format, correlation-id propagation, redaction, debug-flag default
└── features/
    └── ...                    # existing per-slice tests unaffected
```

**Structure Decision**: Single existing FastAPI project (`app/`), unchanged
top-level layout. Logging is added as cross-cutting infrastructure under
`app/core/` — the same location as `config.py`, `db.py`, and `security.py` —
consistent with Principle V, which reserves `app/features/*` for vertical,
self-contained feature slices and keeps shared infrastructure out of them.
Feature slices are touched only to swap their existing `logging.getLogger`
calls for the new shared `get_logger()`; no feature slice gains new logging
*behavior* beyond what FR-001–FR-011 require service-wide.

## Complexity Tracking

*No violations — table intentionally omitted.*
