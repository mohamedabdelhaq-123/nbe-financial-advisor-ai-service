# Phase 0 Research: Text Embedding Service

All unknowns from the Technical Context were resolved by inspecting the current codebase and the already-installed dependency tree — no external research was required.

## Decision: Core service shape mirrors `get_chat_model`

**Decision**: Add `app/core/embedding.py` with `get_embedding_model() -> Embeddings` (the `langchain_core.embeddings.Embeddings` interface), following the same cached-factory-function shape as `get_chat_model` in `app/core/llm.py` (see the later "Cache key MUST include `settings.use_mock_llm`" decision below for the exact caching mechanics, amended after `/speckit-analyze`).

**Rationale**: `app/core/llm.py` already establishes the precedent for cross-feature, provider-agnostic model access in this codebase: a single cached factory function, config-driven, never instantiated ad hoc at a call site. Embeddings are the same shape of problem (an external AI provider call needed by multiple feature slices — currently just `recommendations`, later possibly others), so reusing the identical pattern keeps the codebase consistent rather than inventing a second convention.

**Alternatives considered**: A class-based `EmbeddingProvider` service — rejected as unnecessary indirection (Constitution VIII: no speculative abstraction) when a single function matches the existing `get_chat_model` precedent exactly.

## Decision: Real embeddings via `langchain_openai.OpenAIEmbeddings`, its own base URL/key

**Decision**: In real mode, `get_embedding_model()` returns `OpenAIEmbeddings(base_url=settings.embedding_base_url, api_key=SecretStr(settings.embedding_api_key), model=settings.embedding_model_name, dimensions=settings.embedding_dimensions)` — `embedding_base_url`/`embedding_api_key` are their own `Settings` fields, independent of `openai_base_url`/`openai_api_key` (amended post-implementation; the first pass reused the LLM ones directly).

**Rationale**: `langchain-openai` is already a direct dependency (used for `ChatOpenAI`). `OpenAIEmbeddings` is the library's native embeddings client — confirmed importable in the current environment. Reusing the chat provider's `openai_base_url`/`openai_api_key` outright (the original design) silently assumed the embedding provider always lives at the same endpoint as chat — false in a real deployment where chat is pointed at a self-hosted vLLM instance that serves no embedding model, or the two are simply billed/rotated separately. Giving embeddings its own `base_url`/`api_key` (own defaults, own fail-fast check — see data-model.md) preserves the same OpenAI/self-hosted-vLLM interchangeability Constitution VI requires for chat, independently for embeddings; it still reuses `use_mock_llm` as the one shared mock-mode toggle (see the caching decision above), since mock-vs-real is a service-wide affordance while the *endpoint* is provider-specific.

**`check_embedding_ctx_length=False` (found testing against a real provider)**: `OpenAIEmbeddings` defaults to a "length-safe" strategy — it tokenizes input via `tiktoken` and sends **token-ID arrays** to the `/embeddings` endpoint rather than raw text, chunking/re-averaging as needed to respect a model's context window. This is correct for genuine OpenAI models but broke immediately against a real OpenAI-compatible-but-non-OpenAI provider (`perplexity/pplx-embed-v1-0.6b` via OpenRouter): the SDK raised `ValueError: No embedding data received` with zero further detail. Root-caused by comparing raw HTTP requests: the provider returns `{"error": "Invalid input format. Perplexity embeddings only support string inputs. Token arrays and image inputs are not supported."}` for token-array input, while raw string input (with `dimensions` and/or `encoding_format=base64`, tested independently and combined) succeeds every time. Setting `check_embedding_ctx_length=False` makes the client send raw text unconditionally, fixing this — and verified end-to-end against the real provider afterward (2 texts, 768-dim vectors each, both through `get_embedding_model()` directly and through the live `POST /internal/embeddings` endpoint). This also has zero downside for this feature's own contract: FR-011/the spec's Assumptions already say no client-side length limits are imposed beyond what the provider itself enforces, so an over-length input should surface as a real provider error rather than being silently pre-chunked by the client — which is exactly what disabling this gets us, independent of the OpenRouter compatibility issue that surfaced it.

**Alternatives considered**: Hand-rolled `httpx` calls to `/v1/embeddings` — rejected outright; this is precisely the hand-rolled implementation Constitution VIII and the user's request say to avoid when a library already solves it.

## Decision: Mock embeddings via `langchain_core.embeddings.DeterministicFakeEmbedding`

**Decision**: In mock mode (`settings.use_mock_llm is True`), `get_embedding_model()` returns `DeterministicFakeEmbedding(size=settings.embedding_dimensions)`.

**Rationale**: Confirmed present and importable in the currently installed `langchain-core` (`from langchain_core.embeddings import DeterministicFakeEmbedding`). It hashes the input text into a seed and produces the same vector for the same text every time (verified: `embed_query("hello world")` called twice returns identical vectors; a different string returns a different vector), which satisfies FR-004 and SC-005 with zero hand-rolled code — directly replacing `app/features/embed/service.py`'s existing hand-rolled `hashlib`-based `_mock_vector` helper.

**Alternatives considered**: `langchain_core.embeddings.FakeEmbeddings` (random, non-deterministic per instantiation) — rejected because FR-004 requires the *same* text to always produce the *same* vector; `DeterministicFakeEmbedding` is the library-provided primitive built for exactly this requirement.

## Decision: Reuse `settings.use_mock_llm` as the single mock-mode switch (no new flag)

**Decision**: `get_embedding_model()` branches on the existing `settings.use_mock_llm`, not a new dedicated `use_mock_embeddings` flag.

**Rationale**: `tests/conftest.py` already forces `USE_MOCK_LLM=1` for the entire test suite; reusing it means embedding tests get mock mode for free with zero new environment plumbing, and "mock external AI provider access" stays a single toggle for the whole service rather than two flags that could drift out of sync. Introducing a second flag would be exactly the kind of speculative config surface Constitution VIII warns against, with no concrete requirement driving the need to decouple chat and embedding mocking independently.

**Alternatives considered**: A dedicated `use_mock_embeddings` setting (mirroring `use_mock_mineru`'s per-integration-flag pattern) — rejected for now as unneeded; can be added later if a real need to decouple the two emerges.

## Decision: `get_embedding_model(dimensions: int | None = None)` — variable, config-defaulted

**Decision**: `embedding_dimensions: int = 768` remains a new `Settings` field (the *default*), but `get_embedding_model()` takes an optional `dimensions: int | None = None` parameter; when omitted it falls back to `settings.embedding_dimensions`. Both the real (`OpenAIEmbeddings(dimensions=...)`) and mock (`DeterministicFakeEmbedding(size=...)`) branches receive the resolved value.

**Rationale**: Per explicit user direction, embedding dimension must be a caller-overridable parameter rather than a single fixed value baked into the function — a future feature slice may need a different dimensionality than `recommendations`' existing `Vector(768)` column without having to change the shared default (FR-014). Keeping `settings.embedding_dimensions` as the *default* (rather than removing it) preserves the zero-argument call `get_embedding_model()` that `app/features/embed/service.py` uses today, so `recommendations` keeps working unmodified at 768 dimensions unless it's deliberately changed. `OpenAIEmbeddings` already exposes `dimensions` as a first-class Pydantic field (confirmed: `dimensions` is in `OpenAIEmbeddings.model_fields`), and `DeterministicFakeEmbedding`'s `size` field is the mock-side equivalent — both accept it per-instantiation, so no library limitation blocks parameterizing it.

**Alternatives considered**: A single fixed `embedding_dimensions` setting with no per-call override (the original plan) — superseded by explicit user feedback; picking a native-768-dimension provider/model instead of the `dimensions` truncation parameter — rejected as more provider-specific and less portable than `dimensions`, which works uniformly across the `text-embedding-3-*` family and keeps the base-URL-swappable design intact regardless of which dimension a given call requests.

## Decision: Cache key MUST include `settings.use_mock_llm`, not just `dimensions` (amended after `/speckit-analyze`)

**Decision**: `get_embedding_model()` is *not* itself `@lru_cache`d. It resolves `dim = dimensions or settings.embedding_dimensions` and delegates to a private, `@lru_cache`d builder keyed on `(dim, settings.use_mock_llm)`:

```python
@lru_cache(maxsize=None)
def _build_embedding_model(dimensions: int, mock: bool) -> Embeddings:
    if mock:
        return DeterministicFakeEmbedding(size=dimensions)
    return OpenAIEmbeddings(
        base_url=settings.embedding_base_url,
        api_key=SecretStr(settings.embedding_api_key),
        model=settings.embedding_model_name,
        dimensions=dimensions,
    )


def get_embedding_model(dimensions: int | None = None) -> Embeddings:
    return _build_embedding_model(dimensions or settings.embedding_dimensions, settings.use_mock_llm)
```

**Rationale**: `/speckit-analyze` found and empirically confirmed a defect in the original single-key design (`@lru_cache` on `get_embedding_model(dimensions)` alone): since `settings.use_mock_llm` was not part of the cache key, calling `get_embedding_model()` once in mock mode and then again after `settings.use_mock_llm` flips to `False` (e.g. a test monkeypatching it, per `tests/core/test_embedding.py`) silently returns the **stale mock instance** instead of a fresh `OpenAIEmbeddings` — verified with a minimal repro (`lru_cache`-wrapped function called before/after flipping a mock flag on the same `dimensions` argument returns `is`-identical objects). This directly undermined FR-002/FR-010/SC-002 ("switching mock/real requires only a config change") and spec.md's own Edge Case ("does each call reflect the mode active at call time?"), and would have made the real-mode branch unreachable for the rest of a pytest session once any earlier test populated the cache in mock mode for the same `dimensions` value. Splitting the cached builder from the settings-resolving wrapper fixes this: every call re-reads `settings.use_mock_llm` fresh, and the `lru_cache` only memoizes the pure `(dimensions, mock) -> Embeddings` construction, not the settings lookup itself.

**Alternatives considered**: Caching `get_embedding_model` directly with `(dimensions, settings.use_mock_llm)` as its own two-argument signature — rejected because it would force every internal caller to pass `use_mock_llm` explicitly, leaking a config detail into call sites (contradicts FR-001/FR-002's "callers don't branch on mode" intent); calling `get_embedding_model.cache_clear()` in tests that flip the mock flag — rejected as a test-only band-aid that doesn't fix the underlying production design (settings could in principle change post-boot via some future reload path) and would need to be remembered at every such call site.

## Decision: Response schema is a small, hand-written Pydantic mirror of OpenAI's contract — no `openai` SDK dependency

**Decision**: `app/features/embed/schemas.py` defines its own minimal `EmbeddingDatum`, `EmbeddingUsage`, and `EmbeddingResponse` Pydantic models, matching OpenAI's documented embeddings response fields exactly (`object`/`data`/`model`/`usage` and `object`/`embedding`/`index` and `prompt_tokens`/`total_tokens`). The endpoint's `response_model` is this local `EmbeddingResponse`, not `openai.types.CreateEmbeddingResponse`.

**Rationale**: An earlier pass of this plan reused `openai.types.CreateEmbeddingResponse`/`Embedding`/`Usage` directly and added `openai` as an explicit direct dependency solely to import those three classes. On reconsideration (explicit user direction), that's a poor trade: pulling in and pinning an entire SDK as a first-class project dependency — one this codebase otherwise never calls (all real provider access already goes through `langchain-openai`) — to reuse three trivially small, stable, publicly-documented data classes is disproportionate to what it buys. OpenAI's embeddings response shape is a simple, long-stable JSON contract (four top-level fields, two nested objects); hand-writing three small `BaseModel`s that mirror it exactly is normal, idiomatic FastAPI response-model authoring, not the kind of complex/error-prone reimplementation (parsers, retry/backoff clients, tokenizers) Constitution VIII's "prefer a library" guidance is aimed at. `count_tokens` (below) still uses `tiktoken` rather than a hand-rolled counter — that remains a case where the library does real, non-trivial work worth reusing; three flat data classes do not.

**Alternatives considered**: `openai.types.CreateEmbeddingResponse`/`Embedding`/`Usage` as the `response_model` (the prior plan) — reverted; guarantees byte-for-byte fidelity to OpenAI's generated types, but at the cost of an explicit SDK dependency for a benefit (drift protection on three flat fields that haven't changed in years) judged not worth that cost here.

## Decision: Request schema stays a thin, minimal FastAPI model (not hand-rolled duplication)

**Decision**: The *request* side keeps a small `EmbeddingRequest(BaseModel)` in `app/features/embed/schemas.py` — `input: str | list[str]`, `model: str | None = None`, plus one validator implementing FR-008 (reject empty/all-blank input). This is **not** replaced with the SDK's `openai.types.embedding_create_params.EmbeddingCreateParams`.

**Rationale**: `EmbeddingCreateParams` is a `TypedDict` describing what a *client* passes to `openai_client.embeddings.create(**params)` — it is the outbound-call shape, not a request-body validator, and FastAPI needs a Pydantic model (or at least a schema-buildable type) with an actual validation hook to enforce FR-008. It also advertises fields explicitly out of scope here (`Iterable[int]` token-array input, `encoding_format: "base64"` — see the MVP-scope decision above); reusing it as-is would either silently over-promise support we don't implement, or require overriding most of it anyway, at which point it isn't really "reuse." A minimal request model with one business-rule validator is the normal, unavoidable FastAPI integration surface — not a reimplementation of something the library already solves — and is kept intentionally small per Constitution VIII's "stay clean and minimal" clause rather than growing into a parallel copy of the SDK's params type.

**Alternatives considered**: Accepting `EmbeddingCreateParams` (TypedDict) directly as the FastAPI body type — rejected: no validation hook for FR-008, and implicitly advertises unsupported request fields.

## Decision: `usage` token counts via `tiktoken`

**Decision**: The response's OpenAI-shaped `usage.prompt_tokens`/`usage.total_tokens` are computed with `tiktoken` (already an installed transitive dependency of `langchain-openai`), not a hand-rolled word-count heuristic.

**Rationale**: `langchain_core.embeddings.Embeddings.aembed_documents` returns only vectors, no usage metadata — the OpenAI-shaped response contract this feature must match (FR-006) requires a `usage` object, so it must be computed independently. `tiktoken` is the actual tokenizer OpenAI's API uses, already present in the dependency tree, and avoids a hand-rolled approximation (Constitution VIII).

**Alternatives considered**: `len(text.split())` or `len(text) // 4` heuristics — rejected as an inaccurate, hand-rolled reimplementation of something a well-tested library already does exactly right.

## Decision: Endpoint stays inside the existing `embed` feature slice, at `/internal/embeddings`

**Decision**: No new feature slice. Add `router.py` (prefix `/internal/embeddings`, `POST` root, `require_token`-guarded) and `schemas.py` to the existing `app/features/embed/` directory; register in `app/main.py` alongside the other feature routers.

**Rationale**: Explicit user direction this planning round: "since we have a ready embed feature, use it, but we should have the core service also." `app/features/embed/service.py` already exists and is already the interface `recommendations` depends on — extending it in place (rather than creating e.g. `app/features/embedding/`) avoids a duplicate slice for the same capability. The `/internal/<feature>` URL prefix matches every other feature router (`/internal/plan`, `/internal/ingestion`, `/internal/recommendations`); FR-006's "match OpenAI's embeddings API" requirement is about request/response *body shape* (`input`/`model` in, `object`/`data`/`model`/`usage` out), not the literal `/v1/embeddings` path, which is an implementation detail the spec deliberately leaves unspecified.

**Alternatives considered**: A new `app/features/embedding/` slice — rejected per explicit user direction to reuse the existing one; mounting at OpenAI's literal path `/v1/embeddings` — rejected as inconsistent with this codebase's own `/internal/*` convention and unnecessary for backend-to-backend compatibility (the backend already targets this service's base URL, not OpenAI's).

## Decision: No retries, no `encoding_format=base64` support (MVP scope) — but request-level `dimensions` IS supported

**Decision**: A provider error propagates immediately as an error response (FR-011, already resolved in `/speckit-clarify`). The request schema accepts OpenAI's `input`, `model`, and `dimensions` fields:
- `model` is accepted but not used to switch providers (echoed back as the configured model name in the response, consistent with the spec's Assumption that a single embedding configuration is active at a time).
- `dimensions` (optional `int`, `gt=0` when present) is passed straight through to `embed_texts(texts, dimensions=body.dimensions)` → `get_embedding_model(dimensions=...)`. Omitting it resolves to `settings.embedding_dimensions` (768, matching the existing `recommendations` pgvector column), so existing callers that don't pass it are unaffected.

Still out of scope for this pass: `encoding_format: "base64"` (float arrays only) and token-array `input` (`Iterable[int]`/`Iterable[Iterable[int]]`, string input only).

**Rationale**: `get_embedding_model()`'s dimension parameter was made caller-overridable per explicit user direction (see the dimensions decision above) specifically so a future feature slice can request a different vector size than `recommendations`' fixed 768 — exposing the same override at the HTTP layer is the natural extension of that decision, and matches OpenAI's own request contract's `dimensions` field exactly (no gap between "what we accept" and "what OpenAI accepts" on this field). It's additive and backward-compatible: omitting `dimensions` keeps the default 768 behavior the `recommendations` feature already relies on. `encoding_format=base64` and token-array input remain deliberately out of scope — no current consumer need, and both can be added later as additive fields without breaking this contract.

**Alternatives considered**: Keeping `dimensions` fixed server-side only (the earlier plan) — superseded by explicit user feedback; validating `dimensions` against a fixed allow-list (e.g. `{256, 768, 1536}`) — rejected as an arbitrary hand-rolled restriction OpenAI's own API doesn't impose (it accepts any positive integer up to the model's native size and errors itself if it's invalid) — invalid values are left to surface as a provider error via the existing FR-011 no-retry error path rather than reimplementing OpenAI's own range validation.
