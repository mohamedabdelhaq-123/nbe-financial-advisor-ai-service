# Implementation Plan: Transaction Embedding by ID

**Branch**: `008-embed-transactions` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-embed-transactions/spec.md`

## Summary

Expose an authenticated, backend-facing endpoint that accepts a list of
transaction IDs, builds a structured merchant/category/amount/currency/date
summary for each, computes an embedding via the service's existing shared
embedding capability, and writes each vector directly into that transaction's
`embedding` column in the backend DB — all-or-nothing per request, with one
audit log entry per successful call. This is the first write path this service
opens against the backend DB, made possible by a narrow, pre-existing DB grant
(`UPDATE (embedding) ON transactions`, plus full CRUD on `monthly_summaries` for
future use) provisioned specifically for this purpose.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 (async, `asyncpg`), `pgvector`,
existing `app.features.embed.service.embed_texts` (shared embedding entry point),
existing `app.core.audit.record_audit`

**Storage**: PostgreSQL — backend DB (`transactions` table, read + narrow write via
`ai_readonly`) and this service's own DB (`ai_audit_log`, write)

**Testing**: `pytest` + `pytest-asyncio`, Testcontainers `pgvector/pgvector:pg16`
(per `tests/conftest.py`'s `own_pg` fixture, which also stands in for the backend
`transactions` table in tests); mock-mode embedding (`USE_MOCK_LLM=1`) — no real
provider or network call in tests, per Constitution Principle I

**Target Platform**: Linux server (containerized FastAPI service)

**Project Type**: Web service (single internal API, no frontend)

**Performance Goals**: Synchronous request/response; no explicit latency target
beyond "one call, one definitive result" (SC-001) — batch is capped at 500 IDs
specifically to keep worst-case latency bounded without needing async job
infrastructure

**Constraints**: All-or-nothing batch semantics (FR-006, FR-010) implemented via a
single backend DB transaction; the backend DB role's `default_transaction_read_only
= on` default means the write transaction must explicitly issue `SET TRANSACTION
READ WRITE` before its `UPDATE`s (see [research.md](./research.md))

**Scale/Scope**: One new endpoint, one new feature slice; up to 500 transaction IDs
per request

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Mandatory Automated Testing | Integration tests will run against real Postgres via Testcontainers (extending the existing `own_pg`/`transactions`-table pattern); embedding calls stay mock-first (`USE_MOCK_LLM=1`); no live provider or backend call in CI | PASS |
| II. Security & Secrets Discipline | Endpoint sits behind `require_token` like every other `/internal/*` route; no new secrets introduced | PASS |
| III. Data Protection & Compliance | Egress is limited to exactly the fields needed for the summary (merchant/category/amount/currency/date), matching the existing monthly-summary pattern (clarified: no redaction, consistent with that precedent); every successful write is audit-logged (FR-012) | PASS |
| IV. Data Ownership & Access Boundaries | This feature writes to `transactions.embedding` only. As of Constitution v2.2.0, this is one of the two explicitly enumerated write exceptions (the other being `monthly_summaries`), backed by the matching `ai_readonly` GRANT and requiring the per-transaction `SET TRANSACTION READ WRITE` override to stay scoped to this feature's single write transaction (see research.md). No broader write surface is introduced. | PASS |
| V. Feature-Bounded Modular Architecture | New self-contained slice `app/features/transactions/` (router, schemas, service, tests); reuses `embed` and `audit` slices through their service interfaces only, never reaching into their internals | PASS |
| VI. LLM & Agent Architecture | No agent/LLM involved; uses the existing embedding capability exactly as configured elsewhere (FR-011), no new provider wiring | PASS |
| VII. Operational Readiness | No change to `/health`/`/ready`; config (embedding provider/model/dims) already validated at startup by existing settings | PASS |
| VIII. Library-First, Minimal Implementation | Atomicity is delegated to a native Postgres transaction rather than hand-rolled compensating writes (see research.md); reuses `embed_texts` and `record_audit` rather than reimplementing either | PASS |

**Gate status**: All gates pass. (Constitution v2.2.0 formally enumerates this
feature's `transactions.embedding` write path as an authorized exception to
Principle IV's read-only default — see Complexity Tracking for the deviation
history this amendment resolved.) Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/008-embed-transactions/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md         # Phase 1 output (/speckit.plan command)
├── quickstart.md         # Phase 1 output (/speckit.plan command)
├── contracts/
│   └── transactions-embed.md   # Phase 1 output (/speckit.plan command)
└── tasks.md              # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── features/
│   ├── transactions/               # NEW — this feature's slice
│   │   ├── __init__.py
│   │   ├── router.py                # POST /internal/transactions/embed
│   │   ├── schemas.py               # TransactionEmbedRequest / Result
│   │   └── service.py               # fetch → summarize → embed → write (atomic) → audit
│   ├── embed/                       # existing — reused via embed_texts()
│   ├── analytics/                   # existing — untouched, no overlap
│   └── audit/                       # existing — reused via record_audit()
├── backend_db/
│   └── models/
│       └── statements.py            # existing — Transaction, TRANSACTION_EMBEDDING_DIM (no change)
├── core/
│   ├── audit.py                     # existing — record_audit() (no change)
│   ├── db.py                        # existing — get_own_session() (no change)
│   └── security.py                  # existing — require_token, ERROR_RESPONSES (no change)
├── backend_db/__init__.py           # existing — get_backend_session() unchanged; its
│                                     #   module docstring is amended (T019) to stop
│                                     #   claiming zero write paths exist, since this
│                                     #   feature's write override lives in the new
│                                     #   service code, not in this shared dependency
└── main.py                          # add: app.include_router(transactions.router)

tests/
└── features/
    └── transactions/                # NEW
        ├── test_transactions_router.py
        └── test_transactions_service.py
```

**Structure Decision**: New vertical slice `app/features/transactions/`
(Constitution Principle V), mirroring the existing `embed`/`analytics`/`recommendations`
slices exactly (router + schemas + service, no feature-owned models since no new
table is introduced). It depends on `embed` and `audit` only through their public
service functions (`embed_texts`, `record_audit`), never their internals. No
changes to `app/backend_db/models` are needed — `Transaction` and
`TRANSACTION_EMBEDDING_DIM` already exist and already expose every field this
feature reads.

## Complexity Tracking

*No open violations.* This section previously flagged a Principle IV deviation
(this feature writes to a backend-owned table). That was resolved by a
constitution amendment rather than a code-side justification: Constitution
v2.2.0 formally enumerates `transactions.embedding` (UPDATE only) and
`monthly_summaries` (full CRUD) as the two DB-role-backed, explicitly
authorized exceptions to Principle IV's read-only-by-default rule — this
feature's write surface matches the first exception exactly and introduces
no broader access. See the constitution's Sync Impact Report (v2.1.0 →
v2.2.0) for the amendment rationale.
