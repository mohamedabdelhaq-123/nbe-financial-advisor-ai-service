# Tasks: Text Embedding Service

**Input**: Design documents from `specs/007-embedding-service/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/embeddings-api.md](contracts/embeddings-api.md), [quickstart.md](quickstart.md)

**Tests**: Included. Constitution Principle I ("Every feature MUST ship with automated unit and
integration tests") makes tests mandatory for this repository, not optional.

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths are exact and relative to the repository root

## Path Conventions

Single project, existing FastAPI service. The core, cross-feature embedding primitive lives in
`app/core/embedding.py` (mirroring `app/core/llm.py`); the HTTP surface and refactored service
stay inside the existing `app/features/embed/` slice, per plan.md's Structure Decision. New tests
live in `tests/core/test_embedding.py` and the new `tests/features/embed/` directory.

No new project dependency is introduced by this feature (the HTTP response schema is hand-written,
not imported from the `openai` SDK — see research.md), so there is no Setup phase.

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Shared config and test scaffolding every user story's implementation needs. No story-specific work starts before this phase is done.

**⚠️ CRITICAL**: No User Story phase can begin until this phase is complete.

- [X] T001 [P] In `app/core/config.py`, add a new `── embeddings ──` settings section immediately after the existing `── LLM ──` section: `embedding_model_name: str = "text-embedding-3-small"` and `embedding_dimensions: int = 768` (the latter documented with a comment noting it must stay 768 by default to match `AiProblemStatement.embedding Vector(768)` in `app/features/recommendations/models.py`, per data-model.md). No new fail-fast startup check is needed — both have safe defaults and reuse the already-validated `openai_api_key`/`openai_base_url`.
- [X] T002 [P] Create `tests/features/embed/__init__.py` (empty), matching the existing `tests/features/recommendations/__init__.py` convention

**Checkpoint**: Settings and test package exist; user story implementation can now begin.

---

## Phase 2: User Story 1 - Internal features obtain embeddings through one shared capability (Priority: P1) 🎯 MVP

**Goal**: Any feature inside this service can call a single shared entry point (`get_embedding_model()` / `embed_texts()`) to get vectors, with mock-vs-real mode resolved internally — no hand-rolled mock vector logic anywhere.

**Independent Test**: Call `get_embedding_model()` and `embed_texts()` directly in mock mode; confirm identical calling code works in both mock and (config-swapped) real mode, and that the existing `recommendations` feature — the current consumer of `embed_texts()` — keeps passing unmodified.

### Tests for User Story 1 ⚠️

> Write these first; they must fail before the corresponding implementation task below.

- [X] T003 [P] [US1] Create `tests/core/test_embedding.py`: in mock mode (`settings.use_mock_llm = True`), assert `get_embedding_model()` returns vectors of length `settings.embedding_dimensions` (768) via `.embed_query(...)`/`.aembed_documents([...])`; assert the same input text embedded twice returns an identical vector and a different text returns a different vector (FR-004); assert `get_embedding_model(dimensions=256)` returns 256-length vectors (independently of the 768-length default call); monkeypatch `settings.use_mock_llm = False` (and a non-placeholder `openai_api_key`) **after** the mock-mode calls above have already run, and assert `get_embedding_model()` (same default `dimensions`) now returns a fresh `OpenAIEmbeddings` instance configured with `settings.embedding_model_name`/`settings.embedding_dimensions` — without making any network call; this ordering deliberately exercises the mode-flip-after-cache-population scenario the T005 cache-key fix addresses
- [X] T004 [P] [US1] Create `tests/features/embed/test_embed_service.py`: assert `embed_texts(["a", "b"])` returns two vectors in the same order as the input (FR-009); assert `embed_texts([])` returns `[]`; assert `embed_texts(["x"], dimensions=256)` returns a vector of length 256 (confirms the parameter is forwarded to `get_embedding_model`); assert nothing in the module references `hashlib` any more (the hand-rolled mock is gone)

### Implementation for User Story 1

- [X] T005 [US1] Create `app/core/embedding.py` with a private `@lru_cache`d `_build_embedding_model(dimensions: int, mock: bool) -> Embeddings` (if `mock`, return `DeterministicFakeEmbedding(size=dimensions)` from `langchain_core.embeddings`; else return `OpenAIEmbeddings(base_url=settings.openai_base_url, api_key=SecretStr(settings.openai_api_key), model=settings.embedding_model_name, dimensions=dimensions)` from `langchain_openai`), plus a public, **uncached** `get_embedding_model(dimensions: int | None = None) -> Embeddings` (docstring mirroring `app/core/llm.py::get_chat_model`'s style) that resolves `dim = dimensions or settings.embedding_dimensions` and returns `_build_embedding_model(dim, settings.use_mock_llm)`. The cache key MUST include `settings.use_mock_llm` (not `dimensions` alone) — a single-key design was found and fixed during `/speckit-analyze`: it let a stale cached instance survive a mock→real settings flip (see research.md's amended caching decision) — makes T003 pass (depends on T001)
- [X] T006 [US1] Refactor `app/features/embed/service.py`: delete the hand-rolled `_mock_vector`/`hashlib`-based mock entirely; change `embed_texts` to `async def embed_texts(texts: list[str], dimensions: int | None = None) -> list[list[float]]` — return `[]` immediately for an empty `texts` list, else `return await get_embedding_model(dimensions=dimensions).aembed_documents(texts)` — makes T004 pass (depends on T005)
- [X] T007 [US1] Run `uv run pytest tests/features/recommendations -q` and confirm all tests still pass unmodified — verifies `embed_texts()`'s refactored implementation preserves the call signature `recommendations/service.py` already depends on (depends on T006)

**Checkpoint**: The core embedding capability is fully functional and independently testable — any feature can call `get_embedding_model()`/`embed_texts()` with zero mock-handling code of its own, and `recommendations` is unaffected.

---

## Phase 3: User Story 2 - Backend submits text and receives embeddings over an API (Priority: P1)

**Goal**: The backend can `POST /internal/embeddings` with one or more texts and get back embeddings shaped exactly like OpenAI's embeddings API response.

**Independent Test**: Send authenticated HTTP requests (single input, batch input, empty input, unauthenticated) to the endpoint and verify status codes and response shape per [contracts/embeddings-api.md](contracts/embeddings-api.md).

### Tests for User Story 2 ⚠️

- [X] T008 [P] [US2] Create `tests/features/embed/test_embed_router.py`: `401` without a Bearer token (FR-007); `200` with token + `{"input": "text"}` → `data` has exactly one embedding entry shaped `{"object": "embedding", "embedding": [...], "index": 0}` with `embedding` of length 768, `model == settings.embedding_model_name`, `usage.prompt_tokens > 0` and `usage.total_tokens == usage.prompt_tokens`; `200` with `{"input": ["a", "b"]}` → two `data` entries with `index` 0 and 1 in submitted order (FR-009); `422` with `{"input": []}` and with `{"input": ["   "]}` (FR-008); `422` with `{"input": "x", "dimensions": 0}`; `200` with `{"input": "x", "dimensions": 256}` → returned `embedding` has length 256; `502` when `embed_texts` is monkeypatched to raise, confirming a single call with no retry (FR-011)

### Implementation for User Story 2

- [X] T009 [P] [US2] Create `app/features/embed/schemas.py` with:
  - `EmbeddingRequest(BaseModel)`: `input: str | list[str]`, `model: str | None = None`, `dimensions: int | None = Field(default=None, gt=0)`; a `field_validator("input")` that normalizes a bare string to a one-element list, strips whitespace from each entry, drops blank entries, and raises `ValueError` if the resulting list is empty (FR-008)
  - `EmbeddingDatum(BaseModel)`: `object: Literal["embedding"] = "embedding"`, `embedding: list[float]`, `index: int`
  - `EmbeddingUsage(BaseModel)`: `prompt_tokens: int`, `total_tokens: int`
  - `EmbeddingResponse(BaseModel)`: `object: Literal["list"] = "list"`, `data: list[EmbeddingDatum]`, `model: str`, `usage: EmbeddingUsage`

  A small, hand-written mirror of OpenAI's documented embeddings contract (FR-006) — deliberately not imported from the `openai` SDK, since reusing three flat, stable data classes doesn't justify taking on that package as a project dependency (see research.md) (depends on T001; independent of T005/T006)
- [X] T010 [P] [US2] Add `count_tokens(texts: list[str], model: str) -> int` to `app/features/embed/service.py`, using `tiktoken.encoding_for_model(model)` and falling back to `tiktoken.get_encoding("cl100k_base")` on `KeyError` (a self-hosted/non-OpenAI `embedding_model_name` won't resolve via `encoding_for_model`); returns the sum of encoded-token counts across all `texts` — no hand-rolled word/character heuristic (depends on T006)
- [X] T011 [US2] Create `app/features/embed/router.py`: `router = APIRouter(prefix="/internal/embeddings", tags=["embed"], dependencies=[Depends(require_token)])`; `POST ""` handler taking `body: EmbeddingRequest`, calling `vectors = await embed_texts(body.input, dimensions=body.dimensions)` wrapped in `try/except Exception as exc: raise HTTPException(502, detail="Embedding provider unavailable") from exc` (FR-011 — no retry; FR-012 — text is embedded as-is, no PII detection/redaction is performed; FR-013 — no audit-log entry is recorded for this stateless call); build and return `EmbeddingResponse(object="list", data=[EmbeddingDatum(embedding=v, index=i, object="embedding") for i, v in enumerate(vectors)], model=settings.embedding_model_name, usage=EmbeddingUsage(prompt_tokens=n, total_tokens=n))` where `n = count_tokens(body.input, settings.embedding_model_name)`; set `response_model=EmbeddingResponse` and `responses={**ERROR_RESPONSES}` — makes T008 pass (depends on T009, T010)
- [X] T012 [US2] Register the router in `app/main.py`: add `from app.features.embed import router as embed` alongside the other feature-router imports and `app.include_router(embed.router)` alongside the other `app.include_router(...)` calls (depends on T011)

**Checkpoint**: User Stories 1 AND 2 both work independently — the backend can call `POST /internal/embeddings` and get an OpenAI-shaped response end-to-end.

---

## Phase 4: User Story 3 - Consistent, deterministic behavior in test and CI environments (Priority: P2)

**Goal**: Prove the determinism guarantee (SC-005) holds through the full HTTP stack, not just at the core-service level.

**Independent Test**: `POST` the same text to the endpoint twice in mock mode and confirm both responses' `embedding` arrays are byte-for-byte identical; a different text yields a different vector.

### Tests for User Story 3 ⚠️

- [X] T013 [P] [US3] In `tests/features/embed/test_embed_router.py`, add a determinism test: `POST /internal/embeddings` with `{"input": "same text"}` twice in mock mode and assert `data[0]["embedding"]` is identical across both responses; `POST` with a different input and assert its `embedding` differs from both — proves SC-005 end-to-end through the router, not only at the `get_embedding_model()` level already covered by T003 (depends on T011)

**No separate implementation task**: this story's guarantee comes entirely from US1's `DeterministicFakeEmbedding`-backed `get_embedding_model()` (T005) — this phase only adds the cross-layer proof that the guarantee survives through the router.

**Checkpoint**: All three user stories are independently functional and verified — the feature is complete.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T014 [P] Run Ruff, `black --check`, and `mypy` across all new/changed files (`app/core/config.py`, `app/core/embedding.py`, `app/features/embed/**`, `app/main.py`, `tests/core/test_embedding.py`, `tests/features/embed/**`) and fix any violations
- [X] T015 [P] Run `uv run pytest tests/core/test_embedding.py tests/features/embed tests/features/recommendations -q` and confirm everything passes — the offline unit-test steps of [quickstart.md](quickstart.md)
- [X] T016 Run quickstart.md §3's HTTP curl sequence against a locally running `uv run uvicorn app.main:app` in mock mode and confirm the `401` → `200` → `200` → `422` sequence matches [contracts/embeddings-api.md](contracts/embeddings-api.md)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — start immediately; BLOCKS all user stories
- **User Story 1 (Phase 2)**: Depends on Foundational only
- **User Story 2 (Phase 3)**: Depends on Foundational. T010 (extends `service.py`), T011 (router, calls `embed_texts()`), and T012 (registration) depend on US1's implementation (T005, T006) having landed; T009 (`schemas.py`) does not touch any US1 file and has no code dependency on T005/T006, so it can genuinely start alongside US1 if staffed in parallel
- **User Story 3 (Phase 4)**: Depends on US2's router (T011) existing — it adds an HTTP-level test, not new implementation
- **Polish (Phase 5)**: Depends on all three user stories being complete

### User Story Dependencies

- **US1 (P1)**: No dependency on US2/US3; independently testable as soon as Foundational is done
- **US2 (P2)**: Functionally depends on US1's `embed_texts()` (its router calls it directly) — sequenced after US1's implementation, though independently testable per its own Independent Test criteria
- **US3 (P2)**: Depends on US2's router existing to add the cross-layer test; the guarantee itself was already delivered by US1

### Within Each User Story

- Tests are written first and must fail before the paired implementation task
- `app/core/embedding.py` (US1) precedes `app/features/embed/service.py`'s refactor (US1), which precedes `app/features/embed/router.py` (US2), which precedes `app/main.py` registration (US2)

### Parallel Opportunities

- T001, T002 (Foundational) can run in parallel
- T003, T004 (US1 tests) can run in parallel with each other
- T009, T010 (US2 implementation) touch different files (`schemas.py` vs `service.py`) and can run in parallel with each other; T010 must wait for T006 (US1) to have landed first, but T009 has no dependency on T005/T006 and could start even earlier
- T014, T015 (Polish) can run in parallel; T016 is sequential (a live, manual validation run)

---

## Parallel Example: User Story 1

```bash
# Launch the test-writing tasks for User Story 1 together:
Task: "Write tests/core/test_embedding.py get_embedding_model() mock/real/determinism/dimension tests"
Task: "Write tests/features/embed/test_embed_service.py embed_texts() tests"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational (blocks everything else)
2. Complete Phase 2: User Story 1
3. **STOP and VALIDATE**: run `uv run pytest tests/core/test_embedding.py tests/features/embed tests/features/recommendations -q` — the shared embedding capability works and `recommendations` is unaffected
4. This is a legitimate MVP for internal consumers, but delivers no value to the backend yet — User Story 2 is required before this feature is externally useful

### Incremental Delivery

1. Foundational → settings + test scaffolding ready
2. Add US1 → validate independently → internal core service ready (MVP for internal callers)
3. Add US2 → validate independently → backend can call the HTTP endpoint
4. Add US3 → validate independently → determinism guarantee proven end-to-end
5. Polish → lint/type-check clean, full quickstart validated

---

## Notes

- [P] tasks touch different files (or independent test cases in the same file) with no unmet dependency
- [Story] labels map every story-phase task to spec.md's US1/US2/US3 for traceability
- US2 and US3 are not fully independent of US1 at the *file/behavior* level (US2's router calls US1's `embed_texts()`; US3 tests US1's mechanism through US2's router) — they remain independently testable per their own Independent Test criteria, matching this repo's precedent for sequentially-dependent-but-independently-testable stories (see `specs/005-statement-normalization/tasks.md` Notes)
- FR-012 (no PII redaction) and FR-013 (no audit log) are satisfied by *absence* of code (T011 deliberately adds neither) rather than by a dedicated task — called out explicitly in T011's description so the omission reads as intentional, not overlooked
- No `openai` SDK dependency is introduced — `EmbeddingResponse`/`EmbeddingDatum`/`EmbeddingUsage` (T009) are hand-written, matching OpenAI's documented response contract exactly without taking on the whole package (see research.md)
- Commit after each task or logical group
- Avoid: vague tasks, unnecessary same-file conflicts, skipping a story's tests before its implementation
