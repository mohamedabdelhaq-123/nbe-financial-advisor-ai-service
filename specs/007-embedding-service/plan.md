# Implementation Plan: Text Embedding Service

**Branch**: `007-embedding-service` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-embedding-service/spec.md`

## Summary

Add a core, cross-cutting embedding capability (`get_embedding_model()` in `app/core/embedding.py`, mirroring the existing `get_chat_model()` in `app/core/llm.py`) that any internal feature can call for text embeddings, with mock mode resolved *inside* the function so callers never branch on mode. Reuse the existing `app/features/embed` slice — already consumed by `recommendations` via `embed_texts()` — to expose an OpenAI-embeddings-API-shaped HTTP endpoint for the backend, and refactor its hand-rolled hashlib mock out in favor of the core service. Both the real and mock embedding models come from LangChain's own primitives (`langchain_openai.OpenAIEmbeddings`, `langchain_core.embeddings.DeterministicFakeEmbedding`) rather than hand-rolled code, per Constitution Principle VIII.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI; `langchain-openai` (`OpenAIEmbeddings`, already a direct dependency); `langchain-core` (`Embeddings`, `DeterministicFakeEmbedding` — already installed transitively via `langchain-openai`, same tier as `ChatOpenAI`'s dependency in `app/core/llm.py`); `tiktoken` (already installed transitively; used to compute the OpenAI-shaped `usage` token counts instead of a hand-rolled counter); `pydantic` / `pydantic-settings`. No new direct dependency is added: the response schema is a small hand-written Pydantic mirror of OpenAI's documented contract rather than an import from the `openai` SDK (see research.md — reusing three flat, stable data classes didn't justify taking on the whole package).

**Storage**: N/A for this feature — it computes and returns vectors, it does not persist them. (The `recommendations` feature separately owns the `ai_problem_statements.embedding` pgvector column and is an *existing, unmodified* consumer of `embed_texts()`.)

**Testing**: pytest + pytest-asyncio + httpx `TestClient`, entirely mock-mode (Constitution Principle I — no real network/provider call in tests). No Testcontainers/Postgres needed for this slice specifically, since it owns no database table.

**Target Platform**: Linux container, same FastAPI service as the rest of the app.

**Project Type**: Single backend web service (internal, Django-facing only).

**Performance Goals**: No explicit target beyond standard internal-service expectations (confirmed low-impact/out of scope during `/speckit-clarify`).

**Constraints**:
- `get_embedding_model(dimensions: int | None = None)` takes dimension as an overridable parameter (default read from `settings.embedding_dimensions` = 768), threaded all the way through `embed_texts(texts, dimensions=None)` and the HTTP request's optional `dimensions` field; the *default* (omitted `dimensions`) MUST stay 768 to remain compatible with the existing `ai_problem_statements.embedding Vector(768)` column already populated via `embed_texts()` — changing *that* column's dimensionality would require a data migration + re-embedding, which is out of scope here. Callers (internal or via HTTP) that need a different size pass `dimensions` explicitly.
- No automatic retries on provider failure (FR-011, resolved in `/speckit-clarify`) — a provider error surfaces to the caller immediately.
- No server-side PII redaction (FR-012) and no audit-log entry per call (FR-013) — both explicit clarified decisions.

**Scale/Scope**: One new core module (`app/core/embedding.py`), two new files in the existing `app/features/embed` slice (`router.py`, `schemas.py`), a refactor of its existing `service.py`, two new `Settings` fields, and one new router registration in `app/main.py`. No new feature slice is created.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|---|---|
| I. Mandatory Automated Testing | PASS — new unit tests for `get_embedding_model()` and `embed_texts()`, plus router tests (auth + shape), all mock-mode only, mirroring existing `tests/core/test_config.py`-style and `tests/features/recommendations/test_recommendation_router.py`-style tests. No DB table owned by this slice, so no Testcontainers integration test is required for it specifically. |
| II. Security & Secrets Discipline | PASS — reuses the existing `require_token` Bearer dependency already applied to every other `/internal/*` route. `embedding_api_key`/`embedding_base_url` are new, independent secrets (amended post-implementation — the first pass reused `openai_api_key`/`openai_base_url`, which incorrectly assumed the embedding provider always shares the chat provider's endpoint), fail-fast-checked at startup exactly like the LLM ones. |
| III. Data Protection & Compliance | PASS (scoped by clarification) — FR-012 (no server-side PII redaction, caller's responsibility) and FR-013 (no audit-log entry, stateless transformation) were explicitly decided in `/speckit-clarify` against this principle's text; documented as deliberate scope, not an oversight. |
| IV. Data Ownership & Access Boundaries | N/A — this feature performs no database reads or writes. |
| V. Feature-Bounded Modular Architecture | PASS — the core, cross-feature embedding primitive lives in `app/core` (the same place `get_chat_model` lives), matching the existing precedent that provider access shared by multiple feature slices belongs in core, not inside one feature. The HTTP-facing piece stays inside the `embed` feature slice's own router/schemas/service; `recommendations` keeps consuming `embed_texts()` through that slice's service interface exactly as it does today — no slice reaches into another's internals. |
| VI. LLM & Agent Architecture | N/A — this principle's text (Maestro orchestrator, sub-agents, chat threads) is specific to the chat/agent path, not embeddings; not a gate this feature is bound by. Followed voluntarily anyway: `get_embedding_model` mirrors `get_chat_model`'s mandated pattern (provider access behind a configurable base URL/model, never hardcoded at a call site). |
| VII. Operational Readiness & Fail-Fast Configuration | PASS — the two new settings (`embedding_model_name`, `embedding_dimensions`) get safe defaults and reuse already-validated-at-boot secrets; no new fail-fast check is required. |
| VIII. Library-First, Minimal Implementation | PASS — this is the feature's central purpose: replace the hand-rolled hashlib mock vector generator with `langchain_core.embeddings.DeterministicFakeEmbedding`, and use `langchain_openai.OpenAIEmbeddings` (with its native `dimensions` parameter) instead of a hand-built HTTP client. The HTTP response schema is a deliberate, scoped exception: three small, stable Pydantic models mirroring OpenAI's documented contract, hand-written rather than importing the `openai` SDK — judged normal FastAPI response-model authoring, not the complex/error-prone reimplementation (parsers, retry clients, tokenizers) this principle targets; `count_tokens` still uses `tiktoken` rather than a hand-rolled counter for exactly that reason. |

No violations. Complexity Tracking table intentionally omitted (nothing to justify).

## Project Structure

### Documentation (this feature)

```text
specs/007-embedding-service/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md         # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── embeddings-api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── core/
│   ├── config.py            # MODIFY: add embedding_model_name, embedding_dimensions
│   ├── llm.py                # (existing get_chat_model — pattern this mirrors)
│   └── embedding.py          # NEW: get_embedding_model() — core, cross-feature service
├── features/
│   └── embed/
│       ├── __init__.py       # (existing, empty)
│       ├── service.py        # MODIFY: embed_texts() delegates to get_embedding_model(); drop hand-rolled hashlib mock
│       ├── schemas.py         # NEW: EmbeddingRequest (FR-008 validation) + EmbeddingResponse/EmbeddingDatum/EmbeddingUsage (hand-written mirror of OpenAI's response contract, no openai SDK dependency)
│       └── router.py         # NEW: POST /internal/embeddings, require_token-guarded
└── main.py                   # MODIFY: app.include_router(embed.router)

tests/
├── core/
│   └── test_embedding.py     # NEW: get_embedding_model() mock/real selection, determinism, dimension
└── features/
    └── embed/
        ├── __init__.py        # NEW
        ├── test_embed_service.py   # NEW: embed_texts() unit tests
        └── test_embed_router.py    # NEW: auth guard + OpenAI-shaped request/response
```

**Structure Decision**: Single FastAPI backend project, feature-bounded vertical slices (Constitution V). Per explicit user direction ("since we have a ready embed feature, use it, but we should have the core service also"), no new feature slice is created: the cross-cutting embedding primitive goes into `app/core` next to `get_chat_model`, and the HTTP surface + refactored service stay inside the existing `app/features/embed` slice that `recommendations` already depends on. `recommendations/service.py`'s `embed_texts` import and call signature are unchanged, so it requires no code changes.
