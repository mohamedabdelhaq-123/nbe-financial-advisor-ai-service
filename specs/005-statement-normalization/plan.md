# Implementation Plan: Statement Transaction Normalization

**Branch**: `005-statement-normalization` | **Date**: 2026-07-12 | **Spec**: `specs/005-statement-normalization/spec.md`

**Input**: Feature specification from `specs/005-statement-normalization/spec.md`

---

> **Post-implementation revision**: Real-document validation (a genuine multi-page NBE statement)
> drove a significant architecture change after initial implementation — a chunked LangGraph
> pipeline behind a swappable `NormalizerClient` (matching `MineruClient`'s shape), replacing the
> original single-prompt/inline-branch design. See `research.md` §9–§14 for the full decision
> record and `.specify/memory/constitution.md` v2.1.0 (Principle VIII, added as a direct result of
> this work).
>
> **Post-implementation refactor**: Once the LangGraph revision above landed, `normalizer.py`
> (~420 lines) and `service.py` (~220 lines, two unrelated orchestration concerns) had grown large
> enough to hurt navigation. Both were split into folder modules along their natural seams — no
> behavior change, package `__init__.py` re-exports the same public names each had before. See
> "Project Structure" below for the final layout.

## Summary

A second endpoint in the existing `ingestion` feature slice that, given a `StatementOcrResult` id,
reads the markdown/content-list artifacts already written by Part 1 (document processing), sends
them to the configured LLM to extract a bank name, account hint, and a list of transactions, flags
each transaction against the user's existing recorded transactions as a likely duplicate or not
(deterministic match, no extra LLM judgment), assigns each transaction a category from a new,
service-owned, prepopulated category table, persists the full result as `normalized.json` to object
storage at the same statement-scoped prefix Part 1 already uses, records one audit-log entry, and
returns `{normalized_json, model_used}` to the caller. Writes no backend-owned table; the caller
(Django) is responsible for persisting the result into its own `statement_normalized` table.

## Technical Context

**Language/Version**: Python 3.12, FastAPI, Pydantic v2 (existing, unchanged)

**Primary Dependencies**: `langgraph` (already present, per Constitution VI — now actually used here, not just reserved for the chat Maestro), `langchain-openai` (`ChatOpenAI.with_structured_output`, `.with_retry`), `aioboto3` (`app.core.storage`), and SQLAlchemy async, all already present. One genuinely new dependency: `beautifulsoup4` (real HTML parsing for table-row chunking, Constitution VIII — not present before this feature).

**Storage**: Own DB (new `categories` table, Alembic-managed) + existing S3-compatible object storage (`settings.storage_s3_ocr_bucket`, same bucket Part 1 already writes to) + existing backend DB (read-only: `StatementOcrResult`, `StatementFiles`, `Transactions`)

**Testing**: pytest, pytest-asyncio, mock-first (Constitution I) — `settings.use_mock_llm` short-circuits the LLM call in tests, matching every other LLM-calling feature; Testcontainers Postgres for the new `categories` migration and audit-row persistence, per the existing `own_pg`/`own_db_url` fixtures

**Target Platform**: Existing Linux container; no new external service (reuses the same OpenAI-compatible endpoint already configured for chat/plan features)

**Performance Goal**: Synchronous call completes within ~60s for a typical multi-page statement (SC-001), matching Part 1's goal

**Constraints**: Zero writes to backend-owned tables (Constitution IV, NON-NEGOTIABLE); Bearer-token auth (Constitution II); fail-fast config (Constitution VII — two new settings, `normalization_max_parallel_chunks` and `normalization_chunk_max_tokens`, both default safely to `1` and `4096` respectively); mock-first CI (Constitution I); model never hardcoded at the call site (Constitution VI); prefer library primitives over hand-rolled code (Constitution VIII, added during this feature)

**Scale/Scope**: One statement normalized per call, triggered by the backend, not a hot path — same call pattern as Part 1

## Constitution Check

*Re-verified against `.specify/memory/constitution.md` v2.1.0 after the post-implementation
LangGraph revision (see note above); originally verified against v2.0.0.*

| Principle | Gate | Status |
|---|---|---|
| **I. Testing** | Unit tests mock the LLM at the `app.core.llm.get_chat_model()` seam (a fake structured-output-capable object) — no real network call in the default test run, `MockNormalizerClient` covers the `settings.use_mock_llm` path used by `test_service.py`. The new `categories` migration and seed data, plus the chunking/aggregation logic, are exercised deterministically; concurrency itself is proven via a peak-in-flight-tracking fake, not real timing. | Pass |
| **II. Security** | New route mounts under the same `require_token`-guarded `ingestion` router as Part 1. | Pass |
| **III. Data Protection** | Privileged action — reads a statement's extracted content and the user's transaction history, calls an LLM, persists a new artifact — so it **MUST** write one `ai_audit_log` row per call, via `app.core.audit.record_audit()` + an explicit commit (same pattern Part 1 established). Only the minimal columns needed for dedup matching are ever selected from `Transactions` — not the full row. | Pass |
| **IV. Data Ownership** | Reads `StatementOcrResult`, `StatementFiles`, and `Transactions` only via the existing generated read-only models; **zero writes** to any backend-owned table (SC-004). The one DB write this feature performs beyond the audit row (`categories`) is a **new own-DB table**, Alembic-managed, in the `ingestion` slice. | Pass |
| **V. Modular Architecture** | Lands in the existing `app/features/ingestion/` slice (a second router path + `normalizer.py`/`categories.py`), not a new slice. | Pass |
| **VI. LLM & Agent Architecture** | LLM access still goes exclusively through `app.core.llm.get_chat_model()` (extended with an optional `max_tokens` override — still the sole construction point, model still never hardcoded at a call site) behind `settings.use_mock_llm`/`settings.model_name`. Now genuinely uses LangGraph (`langgraph.graph.StateGraph`) for the extraction pipeline — previously reserved for the chat Maestro only; this is a data-extraction loop, not a second Maestro, so it doesn't compete with or duplicate that orchestrator. | Pass |
| **VII. Operational Readiness** | Two new settings, `normalization_max_parallel_chunks: int = 1` and `normalization_chunk_max_tokens: int = 4096` — both have safe defaults, no fail-fast requirement added (not required to be set). Health/ready probes untouched. | Pass |
| **VIII. Library-First, Minimal Implementation** *(new in v2.1.0, added as a direct result of this feature)* | Structured output via `ChatOpenAI.with_structured_output` replaces a hand-rolled regex JSON-rescue parser; retries on transient generation failures via `Runnable.with_retry` replace a hand-rolled retry loop; table-row chunking uses a real HTML parser (BeautifulSoup) instead of regex over markup; the `NormalizerClient` Protocol reuses `MineruClient`'s already-established swappable-client shape rather than inventing a second pattern. | Pass |

No violations — Complexity Tracking table omitted.

## Project Structure

### Documentation (this feature)

```text
specs/005-statement-normalization/
├── plan.md                          ← this file
├── research.md                      ← Phase 0 output
├── data-model.md                    ← Phase 1 output
├── quickstart.md                    ← Phase 1 output
├── contracts/
│   └── ingestion-normalize.md       ← Phase 1 output: internal endpoint contract
└── tasks.md                         ← Phase 2 output (/speckit-tasks, not this command)
```

### Source Code (existing repo, additions marked `NEW`)

```text
migrations/versions/
└── a6171cff73ac_add_categories_table.py   # creates + seeds `categories` (own DB, Alembic)

app/
├── core/
│   ├── config.py                    # + normalization_max_parallel_chunks: int = 1
│   │                                  # + normalization_chunk_max_tokens: int = 4096
│   └── llm.py                       # get_chat_model() extended with an optional max_tokens override
├── backend_db/                      # unchanged — StatementOcrResult/StatementFiles/Transactions
│                                     #   already generated/available
├── features/
│   └── ingestion/                   # existing slice (Part 1), extended
│       ├── router.py                 # + POST /internal/ingestion/normalize
│       ├── schemas.py                 # + NormalizeStatementRequest / NormalizeStatementResult
│       ├── categories.py               # Category model (OwnBase) + resolve_category() lookup/fallback
│       ├── mineru_client.py          # unchanged
│       ├── service/                  # NEW (folder module, split from a single service.py)
│       │   ├── __init__.py             # re-exports process_statement, normalize_statement
│       │   ├── process.py              # Part 1: MinerU document processing
│       │   └── normalize.py            # Part 2: normalize_statement() orchestration
│       └── normalizer/               # NEW (folder module, split from a single normalizer.py)
│           ├── __init__.py             # re-exports NormalizerClient/get_normalizer_client/
│           │                             find_duplicate/schemas
│           ├── schemas.py              # ExtraField/ExtractedTransaction/ExtractedStatement/
│           │                             NormalizerClient protocol
│           ├── chunking.py             # OCR-content chunking (BeautifulSoup table splitting)
│           ├── graph.py                # StateGraph extraction loop + LangGraphNormalizerClient
│           ├── mock.py                 # MockNormalizerClient
│           └── duplicates.py           # find_duplicate()
└── main.py                          # unchanged — ingestion.router already mounted

tests/
└── features/
    └── ingestion/                   # existing tests/ dir, extended
        ├── test_router.py           # + normalize endpoint auth/happy-path/422 cases
        ├── test_service.py          # + normalize_statement() unit tests (fakes for LLM/storage/db)
        ├── test_categories.py       # category lookup/fallback + real-DB migration/seed test
        └── test_normalizer.py       # chunking (real HTML fixtures), LangGraph aggregation,
                                        concurrency (peak-in-flight fake), duplicate matching
```

**Structure Decision**: Everything lands in the existing `app/features/ingestion/` slice — no new
top-level feature. `normalizer.py` grew significantly beyond the original plan (a swappable-client
Protocol + two implementations + a LangGraph pipeline, not a single function); once that growth
made a single file hard to navigate, it was split into a `normalizer/` folder module along its
natural seams (schemas, chunking, the LangGraph pipeline, the mock, duplicate matching) — same
public surface, re-exported from `normalizer/__init__.py`, no behavior change (Constitution VIII:
minimal and clean, not fragmented for its own sake — the split tracks real, distinct concerns
rather than being arbitrary). `service.py` similarly split into a `service/` folder module along
its two independent orchestration concerns (`process.py` for Part 1, `normalize.py` for Part 2),
again with the same public names re-exported from `service/__init__.py`. `categories.py` is
unchanged from the original plan. One genuinely new dependency was added to `pyproject.toml`:
`beautifulsoup4` (real HTML parsing, Constitution VIII). Two new config settings:
`normalization_max_parallel_chunks` and `normalization_chunk_max_tokens` (research.md §13). The Alembic migration is unchanged from the
original plan — hand-written `op.create_table(...)`, matching
`a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py`'s established style.

## Post-Design Constitution Re-Check

Re-verified after Phase 1 (data-model.md, contracts/, quickstart.md): no new dependency, table, or
external call was introduced beyond what the Constitution Check above already accounted for. Still
no violations — Complexity Tracking table omitted, matching Part 1's precedent.

## Post-Implementation Constitution Re-Check (v2.1.0)

Re-verified after the LangGraph/chunking/`NormalizerClient` revision (research.md §9–§14): one new
principle (VIII) was added to the constitution *as a direct consequence* of this feature's real-world
validation, not worked around — see the updated Constitution Check table above. One new dependency
(`beautifulsoup4`) and two new settings (`normalization_max_parallel_chunks` and `normalization_chunk_max_tokens`) were introduced, all
already accounted for in the table above. Still no violations.
