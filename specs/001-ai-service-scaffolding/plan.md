# Implementation Plan: AI Service Scaffolding & Full Feature Build

**Branch**: `feature/001-ai-service-scaffolding` | **Date**: 2026-07-10 | **Spec**: `specs/001-ai-service-scaffolding/`

---

## Summary

Full build-out of the NBE AI service from its current skeleton (health/ready probes, a single `/chat` stub, empty Alembic baseline) into a production-ready FastAPI service. Covers:

- Database modelling and Alembic migrations for all AI-owned tables
- Document extraction integration and normalization pipeline
- Embedding service (nomic-embed-text, 768-dim)
- LangGraph Maestro + sub-agents with Postgres checkpointer
- Background analytics jobs (monthly summaries, recurring charges, anomaly detection)
- Recommendation RAG pipeline
- Full internal API surface as agreed with the backend team
- Testcontainers integration tests and CI compliance

Governance is defined in `.specify/memory/constitution.md` and is not restated here.

---

## Technical Context

| Field | Value |
|---|---|
| **Language / Runtime** | Python 3.12, FastAPI, Pydantic v2 |
| **Async I/O** | `async def` routes, SQLAlchemy 2.0 async on `asyncpg` |
| **AI Stack** | LangChain / LangGraph, `langchain-openai` (`ChatOpenAI`) behind configurable base URL |
| **Embedding Model** | `nomic-embed-text` via Ollama — **768 dimensions** for all vector columns |
| **Checkpointer** | `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`) — own DB, Alembic-documented |
| **Packaging** | `uv` + `pyproject.toml` + committed `uv.lock` |
| **Own DB** | PostgreSQL + pgvector (Alembic-managed) |
| **Backend DB** | PostgreSQL — read-only role, separate `DeclarativeBase`, excluded from Alembic |
| **Document Extraction** | MinerU or equivalent (to be decided by the team member responsible for OCR integration) |
| **Testing** | `pytest`, `pytest-asyncio`, `pytest-testcontainers` (real Postgres), mock-first LLM |
| **Linting / Typing** | Ruff (`E`, `F`, `I`), Black (line length 100), mypy |
| **Target Platform** | Linux container, single on-prem machine, fully offline/air-gapped |
| **Constraints** | No live bank integrations; all data from user-uploaded statements; PII masked before any LLM call |

---

## Constitution Check

*Verified against `.specify/memory/constitution.md` v1.0.0 before any implementation.*

| Principle | Gate |
|---|---|
| **I. Testing** | Every endpoint and agent ships with mock-first unit tests + Testcontainers integration tests. No real model calls in CI. |
| **II. Security** | All internal endpoints require Bearer token. Secrets validated at startup. Secret + dependency scanning in CI. |
| **III. Data Protection** | PII masked by Django before reaching this service. All privileged actions logged to audit table. |
| **IV. Data Ownership** | Own tables managed by Alembic. Backend tables accessed through a read-only role via a separate, Alembic-excluded Base. No write paths to backend tables. |
| **V. Modular Architecture** | Feature-bounded vertical slices. No package-by-layer organisation. |
| **VI. LLM & Agent Architecture** | Maestro + sub-agents on LangGraph. Model name and base URL are config-driven. Analytics from background jobs, not on-demand agents. Outputs are retrieval-grounded and PII-safe. |
| **VII. Operational Readiness** | `/health` and `/ready` probes require no auth. Config validated at startup. |

---

## Project Structure

### Documentation (this spec)

```text
specs/001-ai-service-scaffolding/
├── plan.md          ← this file
└── tasks.md         ← granular task list (Phase 1 & 2)
```

### Source Code Layout

All source lives under `app/` as **feature-bounded vertical slices**:

```text
app/
├── core/
│   ├── config.py          ← pydantic-settings (already exists, will be extended)
│   ├── database.py        ← own DB engine + SessionLocal (already exists)
│   ├── backend_db.py      ← read-only backend DB engine (new — separate Base, no Alembic)
│   └── deps.py            ← get_db(), require_token() shared dependencies
│
├── ingestion/             ← SLICE: document → transaction ledger
│   ├── router.py          ← POST /internal/normalize
│   ├── schemas.py
│   ├── extractor.py       ← pdfplumber confidence check + fallback to extraction tool
│   ├── normalizer.py      ← template lookup → deterministic mapping OR LLM inference
│   ├── models.py          ← (no own tables; reads backend statement_files, writes embeddings)
│   └── tests/
│
├── embed/                 ← SLICE: text → vector
│   ├── router.py          ← POST /internal/embed
│   ├── schemas.py
│   ├── service.py         ← nomic-embed-text client, 768-dim
│   └── tests/
│
├── analytics/             ← SLICE: background aggregation jobs
│   ├── router.py          ← POST /internal/analyze/post-ingestion
│   │                         POST /internal/analyze/monthly-summary
│   │                         POST /internal/analyze/anomaly-check
│   ├── schemas.py
│   ├── jobs/
│   │   ├── monthly_summary.py
│   │   ├── recurring_charges.py
│   │   └── anomaly_detection.py
│   ├── models.py          ← reads backend transactions, monthly_summaries; writes embeddings
│   └── tests/
│
├── chat/                  ← SLICE: conversational pipeline (Maestro + SSE)
│   ├── router.py          ← POST /internal/chat  (SSE stream)
│   ├── schemas.py
│   ├── checkpointer.py    ← AsyncPostgresSaver initialisation + setup()
│   ├── graph.py           ← LangGraph graph compile with checkpointer
│   ├── state.py           ← ConversationState TypedDict
│   ├── agents/
│   │   ├── maestro.py
│   │   ├── analysis.py
│   │   ├── planner.py
│   │   └── recommendation.py
│   └── tests/
│
├── plan/                  ← SLICE: budget planner questionnaire
│   ├── router.py          ← POST /internal/plan/question
│   │                         POST /internal/plan/generate
│   ├── schemas.py
│   ├── service.py
│   └── tests/
│
├── recommendations/       ← SLICE: RAG product matching
│   ├── router.py          ← POST /internal/recommendations/match
│   ├── schemas.py
│   ├── models.py          ← ai_problem_statements (own table, Alembic-managed)
│   ├── service.py         ← pgvector HNSW similarity search
│   └── tests/
│
└── main.py                ← FastAPI app factory, router registration, lifespan hook
```

```text
migrations/
├── env.py                 ← already imports own Base only; will add chat/recommendations models
└── versions/
    ├── f4b0592bb954_initial_empty_baseline.py   ← exists
    ├── XXXX_add_ai_owned_tables.py              ← Phase 1 deliverable
    └── XXXX_document_checkpointer_tables.py     ← Phase 1 deliverable
```

```text
tests/
├── conftest.py            ← Testcontainers Postgres fixture, async client
├── test_app.py            ← existing health/ready/auth tests (kept)
└── test_migrations.py     ← existing migration smoke test (kept)
```

---

## Agreed Architectural Decisions

*Outcomes from pre-implementation review — recorded here so no team member re-litigates them.*

| Decision | Resolution |
|---|---|
| **Embedding model & dimensions** | `nomic-embed-text` (Ollama) — **768 dims** for all three vector columns: `transactions.embedding`, `monthly_summaries.embedding`, `problem_statements.embedding`. Schema dimensions of 1024/1536 are superseded by this decision. |
| **Table ownership** | `problem_statements` and `recommendation_logs` are **AI-service-owned** (Alembic-managed). The AI service has READ access to all backend tables via a dedicated read-only Postgres role. It writes ONLY to its own tables and to specific embedding columns (`transactions.embedding`, `monthly_summaries.embedding`) using targeted UPDATE statements. |
| **Embedding column writes** | The AI service writes `transactions.embedding` and `monthly_summaries.embedding` via targeted UPDATE on the backend DB through the read-only role. These are write exceptions documented in `backend_db.py` with explicit comments. |
| **Chat state** | LangGraph `AsyncPostgresSaver` with `thread_id = conversation_id`. Django sends `initial_context` only on the first turn; subsequent turns send `{conversation_id, user_id, message}` only. See `consolidated files/problems-to-solve/Chat_State_Design.md`. |
| **Context window management** | `trim_messages()` keeps last 20 messages in LLM context. Summarisation node activates at 40+ messages. |
| **Document extraction** | pdfplumber (confidence-checked) → fallback to team-selected extraction tool (MinerU or equivalent). Bank name is resolved from the Django upload context (`bank_accounts.bank_name`), not from PDF text. The team member responsible for OCR integration decides the fallback tool. |
| **Bank name detection** | Not extracted from PDF (logos are images). Django passes `bank_name` in the normalize request from the linked `bank_accounts` record. |
| **Langfuse** | Deferred. Not in scope for either phase. |
| **Monthly summaries computation** | Deterministic SQL aggregation in `analytics/jobs/monthly_summary.py` — NOT computed by LLM agents. |
| **SSE proxying** | Backend team's responsibility. AI service streams SSE; Django proxies it using ASGI for that route. |
| **Budget allocations validation** | AI Planner Agent guarantees its output sums to 100% before returning. Django also validates as a second layer. |

---

## Phase 1 — Foundation & Ingestion Pipeline

*Goal: establish the complete data layer, document ingestion, and embedding service so the backend team has working internal endpoints to integrate against.*

### 1.1 Project Infrastructure

- [ ] Migrate from `requirements.txt` to `uv` + `pyproject.toml` (already partially done; verify `uv.lock` is committed and CI uses `uv sync`)
- [ ] Extend `app/core/config.py` with all new settings: `POSTGRES_*`, `OLLAMA_BASE_URL`, `EMBEDDING_MODEL` (default: `nomic-embed-text`), `LLM_BASE_URL`, `LLM_MODEL_NAME`, `AI_SERVICE_TOKEN`, `USE_MOCK_LLM`
- [ ] Add `app/core/backend_db.py`: read-only SQLAlchemy engine + separate `DeclarativeBase` (`BackendBase`), excluded from Alembic. Document the two targeted UPDATE exceptions for embedding columns
- [ ] Extract `require_token()` and `get_db()` into `app/core/deps.py` (remove from `main.py`)
- [ ] Refactor `app/main.py` into an app factory with a `lifespan` context manager for startup/shutdown hooks

### 1.2 Database Modelling & Alembic Migrations

- [ ] Define AI-service-owned SQLAlchemy models:
  - `ai_problem_statements` (`id`, `product_id` [logical FK], `statement_text`, `embedding vector(768)`) in `recommendations/models.py`
  - `ai_recommendation_logs` (`id`, `user_id`, `product_id`, `matched_query`, `similarity_score`, `shown_at`) in `recommendations/models.py`
  - `ai_audit_log` (`id`, `user_id`, `action`, `detail_json`, `created_at`) in a new `audit/models.py` (Constitution III requirement)
- [ ] Register all own models in `migrations/env.py`
- [ ] Generate Alembic migration: `XXXX_add_ai_owned_tables` — creates `ai_problem_statements`, `ai_recommendation_logs`, `ai_audit_log` with HNSW indexes on embedding columns
- [ ] Generate Alembic migration: `XXXX_document_checkpointer_tables` — documents the three LangGraph checkpointer tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) as AI-service-owned (auto-created by `checkpointer.setup()` on startup; migration records ownership)
- [ ] Write backend read-only typed models in `app/core/backend_models.py` (hand-written, not autogenerated): `transactions`, `monthly_summaries`, `bank_accounts`, `bank_statement_templates`, `budgets`, `budget_allocations`, `products`, `users`

### 1.3 Document Extraction & Normalization

- [ ] Implement `ingestion/extractor.py`:
  - pdfplumber confidence check (text yield, table detection, cell fill rate, date/amount parseability)
  - If confidence passes: return structured `{headers, rows}` 
  - If confidence fails: delegate to the configured extraction tool (interface only — concrete tool decided by OCR team member)
  - Layout signature generation: `md5(sorted(normalised_headers))`
- [ ] Implement `ingestion/normalizer.py`:
  - Template lookup: query `bank_statement_templates` by `(bank_name, layout_signature)` via backend read-only DB
  - Template hit → deterministic column mapping, no LLM call
  - Template miss → LLM-inferred column mapping via `langchain-openai`, save new template record (returned to Django for persistence)
  - Map rows to `NormalizedTransaction` schema
  - Arabic month name → ISO date normalisation
- [ ] Implement `POST /internal/normalize` in `ingestion/router.py`
- [ ] Write unit tests (mock LLM, mock DB) and integration tests (Testcontainers) for both paths

### 1.4 Embedding Service

- [ ] Implement `embed/service.py`: async Ollama client wrapping `nomic-embed-text`, batch embedding with configurable chunk size
- [ ] Implement `POST /internal/embed` in `embed/router.py` — accepts `list[str]`, returns `list[list[float]]` (768-dim)
- [ ] Write unit tests (mock embedder) and integration tests

---

## Phase 2 — Agentic Pipelines, Analytics, and Integration

*Goal: deliver the complete conversational AI, budget planner, recommendation engine, and background analytics — fully tested and integrated with the internal API surface.*

### 2.1 LangGraph Chat Infrastructure

- [ ] Implement `chat/state.py`: `ConversationState` TypedDict — `messages`, `user_context`, `stage`, `intent`, `planner_answers`, `questions_asked`, `message_references`
- [ ] Implement `chat/checkpointer.py`: `AsyncPostgresSaver` initialisation; `setup()` called in `lifespan`
- [ ] Implement summarisation node: activates when `len(messages) > 40`, compresses oldest messages into a `SystemMessage` summary
- [ ] Implement `trim_messages()` wrapper: keeps last 20 messages in LLM context window

### 2.2 Maestro Orchestrator & Sub-Agents

- [ ] Implement `chat/agents/maestro.py`: intent parser → routes to Analysis / Planner / Recommendation sub-agent
- [ ] Implement `chat/agents/analysis.py`: reads `monthly_summaries`, `transactions`, `anomaly_flags` from backend DB; answers spending questions; cites source rows in `message_references`; never fabricates figures
- [ ] Implement `chat/agents/planner.py`: multi-turn questionnaire loop (max 7 questions, counter in graph state); generates `BudgetAllocation` list summing to 100%; validates internally before returning
- [ ] Implement `chat/agents/recommendation.py`: pgvector HNSW similarity search on `ai_problem_statements`; returns top-k products with scores
- [ ] Implement `chat/graph.py`: compile LangGraph graph with checkpointer; wire all nodes and edges
- [ ] Implement `POST /internal/chat` in `chat/router.py`: SSE stream, handles `is_first_turn` and `refresh_context` flags
- [ ] Write unit tests for each agent (mock LLM, mock DB) and graph integration tests (Testcontainers)

### 2.3 Budget Planner Endpoints

- [ ] Implement `plan/service.py`: stateless question generator (reads `user_context`, determines next question); plan generator (produces allocations from collected answers)
- [ ] Implement `POST /internal/plan/question` in `plan/router.py`
- [ ] Implement `POST /internal/plan/generate` in `plan/router.py`
- [ ] Write tests

### 2.4 Recommendation RAG Pipeline

- [ ] Implement `recommendations/service.py`: pgvector HNSW similarity search against `ai_problem_statements`; log each match to `ai_recommendation_logs`
- [ ] Implement `POST /internal/recommendations/match` in `recommendations/router.py`
- [ ] Seed script for populating `ai_problem_statements` (admin utility, not a runtime endpoint)
- [ ] Write unit and integration tests

### 2.5 Analytics Background Jobs

- [ ] Implement `analytics/jobs/monthly_summary.py`: deterministic SQL aggregation over `transactions` for a given `(user_id, account_id, month)`; writes result to `monthly_summaries`; generates and writes embedding to `monthly_summaries.embedding`
- [ ] Implement `analytics/jobs/recurring_charges.py`: frequency detection across `transactions`; upserts `recurring_charges`
- [ ] Implement `analytics/jobs/anomaly_detection.py`: statistical outlier detection per category; writes to `anomaly_flags`
- [ ] Implement `POST /internal/analyze/post-ingestion`, `POST /internal/analyze/monthly-summary`, `POST /internal/analyze/anomaly-check` in `analytics/router.py`
- [ ] Write tests (deterministic inputs → deterministic outputs; no LLM involvement)

### 2.6 End-to-End Integration & CI Hardening

- [ ] Update `tests/conftest.py`: Testcontainers Postgres fixture (own DB + backend DB replica), async HTTP test client, mock Ollama embedder fixture, mock LLM fixture
- [ ] Add CI steps: `mypy` type-check, secret scanning (`detect-secrets` or `truffleHog`), dependency vulnerability scanning (`uv audit` or `safety`), container image build verification
- [ ] Verify all existing tests (`test_app.py`, `test_migrations.py`) still pass after refactor
- [ ] Update `.env.example` with all new settings
- [ ] Update `Dockerfile` if any new system dependencies are added by the extraction tool
