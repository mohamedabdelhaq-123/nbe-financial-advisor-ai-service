# Implementation Plan: Statement Document Processor

**Branch**: `004-document-processor` | **Date**: 2026-07-12 | **Spec**: `specs/004-document-processor/spec.md`

**Input**: Feature specification from `specs/004-document-processor/spec.md`

---

## Summary

A new `ingestion` feature slice that, given a `statement_id`, resolves the statement's raw file
location via existing read-only backend DB access, fetches the raw bytes from object storage,
sends them to MinerU (`POST /file_parse`, `response_format_zip=true`), unpacks the returned ZIP
(markdown, `content_list.json`, images), and persists all three artifact kinds to the existing
S3-compatible object-storage backend under a key prefix scoped to the statement. It returns that
prefix and a fixed `"MinerU"` engine label to the caller, records one audit-log entry, and writes
to no backend-owned table. Normalization of the extracted content into transactions is explicitly
out of scope (separate, later capability).

---

## Technical Context

| Field | Value |
|---|---|
| **Language / Runtime** | Python 3.12, FastAPI, Pydantic v2 (existing) |
| **New runtime dependency** | None — `httpx` and `aioboto3` are already in `[project.dependencies]` |
| **External service** | MinerU document parser, `POST {settings.mineru_api_url}/file_parse`, multipart upload, `response_format_zip=true`, credential via `X-Api-Key` header |
| **Object storage** | Existing `app/core/storage.py` (`get_storage_backend()` — aioboto3 S3 client against SeaweedFS); OCR output bucket read from a new `settings.storage_s3_ocr_bucket` setting, never hardcoded |
| **Backend DB access** | Existing `app.backend_db.get_backend_session()` (read-only), querying `StatementFiles` |
| **Own DB access** | Existing `app.core.db.get_own_session()`, writing one `AiAuditLog` row per processing call |
| **Testing** | pytest, pytest-asyncio, mock-first (Constitution I) — via a swappable `MineruClient` interface (real `HttpMineruClient` now; `MockMineruClient` explicitly deferred, see research.md §8); unit tests use an inline test double until it lands |
| **Target Platform** | Existing Linux container; MinerU already wired via `docker-compose.yml` → `compose/mineru/docker-compose.yml` (`mineru-api`, port 8000, profile `api`) |
| **Performance Goal** | Synchronous call completes within ~60s for a typical multi-page statement (SC-001) |
| **Constraints** | Zero writes to backend-owned tables (Constitution IV, NON-NEGOTIABLE); Bearer-token auth (Constitution II); fail-fast config (Constitution VII); mock-first CI (Constitution I) |

---

## Constitution Check

*Verified against `.specify/memory/constitution.md` v2.0.0.*

| Principle | Gate | Status |
|---|---|---|
| **I. Testing** | Unit tests mock the backend session, storage client, and MinerU client (an inline test double implementing the `MineruClient` protocol, pending the deferred `MockMineruClient` — research.md §8). No real network call to MinerU or a real object store in the default test run. | Pass |
| **II. Security** | New router mounts under `require_token`, matching every other internal router. | Pass |
| **III. Data Protection** | This capability performs a **privileged action** (reads a user's statement, calls an external processor, persists extracted content) and therefore **MUST** write one `ai_audit_log` row per call — via the existing `app.core.audit.record_audit()` helper (already used by `chat/service.py`), plus an explicit commit at the call site since that helper only flushes. No LLM/prompt exposure occurs here (normalization/LLM inference is a separate, later capability) so the prompt-PII-masking clause doesn't yet apply; extracted content is written to the same trust boundary (this service's configured object store) the original uploaded document already lives in — no new trust-boundary crossing is introduced. | Pass |
| **IV. Data Ownership** | Reads `StatementFiles` only via the existing generated read-only model; **zero writes** to any backend-owned table (SC-005). The one DB write this feature performs (`ai_audit_log`) is to the service's own, Alembic-managed database. | Pass |
| **V. Modular Architecture** | New `app/features/ingestion/` vertical slice (router/schemas/service/client/tests). The one cross-slice call (writing an audit row) goes through the existing `app.core.audit.record_audit()` helper, not by constructing `AiAuditLog` directly from `ingestion`. | Pass |
| **VI. LLM & Agent Architecture** | N/A — no LLM call in this capability by design (spec FR-011); normalization (where an LLM may eventually be used for column mapping) is explicitly out of scope here. | N/A |
| **VII. Operational Readiness** | New settings (`MINERU_API_URL`, `MINERU_API_KEY`, `USE_MOCK_MINERU`) follow the existing fail-fast pattern in `app/core/config.py` — startup raises if `MINERU_API_URL` is unset and mock mode is off. Health/ready probes untouched. | Pass |

No violations — Complexity Tracking table omitted.

---

## Project Structure

### Documentation (this feature)

```text
specs/004-document-processor/
├── plan.md                          ← this file
├── research.md                      ← Phase 0 output
├── data-model.md                    ← Phase 1 output
├── quickstart.md                    ← Phase 1 output
├── contracts/
│   └── ingestion-process.md         ← Phase 1 output: internal endpoint contract
└── tasks.md                         ← Phase 2 output (/speckit-tasks, not this command)
```

### Source Code (existing repo, additions marked `NEW`)

```text
app/
├── core/
│   ├── config.py                    # + mineru_api_url, mineru_api_key, use_mock_mineru,
│   │                                 #   storage_s3_ocr_bucket
│   └── audit.py                     # unchanged — record_audit() already exists and is reused
│                                     #   as-is (an earlier draft of this plan added a duplicate
│                                     #   app/features/audit/service.py before this was found;
│                                     #   removed once discovered)
├── backend_db/                      # unchanged — StatementFiles already generated/available
├── features/
│   └── ingestion/                   # NEW slice
│       ├── __init__.py
│       ├── router.py                 # POST /internal/ingestion/process
│       ├── schemas.py                 # ProcessStatementRequest / ProcessStatementResult
│       ├── service.py                  # orchestration: lookup → fetch → parse → persist → audit
│       └── mineru_client.py            # MineruClient protocol + HttpMineruClient (X-Api-Key,
│                                         ZIP-mode) + get_mineru_client() factory. MockMineruClient
│                                         is DEFERRED — not part of this feature's initial delivery.
└── main.py                          # + app.include_router(ingestion.router)

tests/
└── features/
    └── ingestion/                   # NEW — tests live at the TOP-LEVEL tests/ tree, matching the
        ├── __init__.py              #   established convention (tests/features/<slice>/), NOT
        ├── test_router.py           #   colocated under app/features/ingestion/tests/ as earlier
        ├── test_service.py          #   drafts of this plan assumed — that assumption was corrected
        └── test_mineru_client.py    #   during implementation once the real layout was visible.

.env.example                          # MINERU_API_URL/MINERU_API_KEY already present — keep as-is;
                                       #   add USE_MOCK_MINERU and STORAGE_S3_OCR_BUCKET only
```

**Structure Decision**: The slice is named `ingestion` (not `document_processing`) to match the
domain vocabulary already used in `specs/001-ai-service-scaffolding/plan.md` for "document →
transaction ledger," and to leave room for a future normalization step to land in the same slice
(e.g. `normalizer.py`, a second router path) without a rename. No new own-DB migration is needed —
`ai_audit_log` was already created by `migrations/versions/a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py`.
No new runtime dependency or `pyproject.toml` change is needed — `httpx` and `aioboto3` are already
present. No `lifespan` change is needed — MinerU is called via a fresh `httpx.AsyncClient` per
request (mirroring `get_storage_backend()`'s own "a new client is opened per call" rationale in
`app/core/storage.py`), not a held singleton. The OCR output bucket is read from a dedicated
`settings.storage_s3_ocr_bucket` setting everywhere `ingestion/service.py` writes an artifact —
the bucket name MUST NOT appear as a string literal in that code, only as a config lookup
(research.md §4). Config setting names (`mineru_api_url`, `mineru_api_key`) match the existing
`.env.example` entries exactly — no renaming. `service.py` depends on the `MineruClient` interface
only, obtained via `get_mineru_client()`; it cannot distinguish the real client from a future mock
one (research.md §8) — the requester is validating against a real, reachable MinerU instance for
now, so building `MockMineruClient` is explicitly deferred past this feature's initial delivery.
