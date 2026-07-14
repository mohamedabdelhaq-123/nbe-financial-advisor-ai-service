# Phase 1 Data Model: Text Embedding Service

No database tables are introduced by this feature (see `spec.md` Assumptions — vectors are computed and returned, not persisted). The entities below are in-memory request/response/config shapes, not persisted models.

## Embedding Model Configuration

Extends `app.core.config.Settings` (`app/core/config.py`). Read once at import time like every other setting.

| Field | Type | Default | Notes |
|---|---|---|---|
| `embedding_base_url` | `str` | `"https://api.openai.com/v1"` | Independent of `openai_base_url` (the chat/LLM setting) — the embedding provider isn't guaranteed to live at the same endpoint (amended post-implementation: the first pass reused `openai_base_url` directly). |
| `embedding_api_key` | `str` | `"__mock__"` | Independent of `openai_api_key`. Fail-fast at startup: raises if still `"__mock__"` when `use_mock_llm` is `False`, mirroring the existing `openai_api_key` check. |
| `embedding_model_name` | `str` | `"text-embedding-3-small"` | Passed to `OpenAIEmbeddings(model=...)` in real mode; echoed back as the `model` field in every response regardless of mode. |
| `embedding_dimensions` | `int` | `768` | **Default** dimension, used when a caller does not pass `dimensions` explicitly to `get_embedding_model()`. Matches `AiProblemStatement.embedding Vector(768)` (`app/features/recommendations/models.py`) so the zero-argument call `get_embedding_model()` stays compatible with the existing `recommendations` feature. A caller needing a different dimension (e.g. a future feature with its own vector column) passes `get_embedding_model(dimensions=N)` explicitly — see "Internal call shape" below. |

Mock/real selection itself is **not** a new field — it reuses the existing `use_mock_llm: bool` setting (see `research.md`).

## Embedding Request

Inbound HTTP request body for `POST /internal/embeddings` (`app/features/embed/schemas.py`).

| Field | Type | Required | Validation | Notes |
|---|---|---|---|---|
| `input` | `str \| list[str]` | Yes | At least one entry after normalizing to a list; every entry, once whitespace-stripped, must be non-empty (FR-008) | A single string is normalized internally to a one-element list before embedding. |
| `model` | `str \| None` | No | — | Accepted for OpenAI-shape compatibility; not used to select a provider/model (single configured model — see spec Assumptions). Ignored if present, does not need to match `embedding_model_name`. |
| `dimensions` | `int \| None` | No | `gt=0` when present | Passed through to `embed_texts(texts, dimensions=...)` → `get_embedding_model(dimensions=...)`. Omitted → defaults to `settings.embedding_dimensions` (768, matching the `recommendations` pgvector column). Out-of-range values (e.g. exceeding the provider's native max) are left to surface as a provider error (FR-011), not pre-validated against a hand-rolled allow-list. |

Rejected requests (empty `input` list, or a list of only blank/whitespace strings) return a `422` with a clear validation error (FR-008, SC-004) — handled by a Pydantic validator rather than hand-rolled request-body inspection in the route body.

## Embedding Response

Outbound HTTP response body. Defined locally in `app/features/embed/schemas.py` as three small Pydantic models mirroring OpenAI's documented embeddings response fields exactly (FR-006) — deliberately *not* imported from the `openai` SDK, to avoid taking on that package as a project dependency just to reuse three flat, long-stable data classes (see `research.md`).

**`EmbeddingResponse`**

| Field | Type | Notes |
|---|---|---|
| `object` | `Literal["list"]` | Fixed value, per OpenAI contract. |
| `data` | `list[EmbeddingDatum]` | One entry per input text, in the same order as submitted (FR-009). |
| `model` | `str` | Set to `settings.embedding_model_name`. |
| `usage` | `EmbeddingUsage` | Token counts computed via `tiktoken` (see `research.md`). |

**`EmbeddingDatum`**

| Field | Type | Notes |
|---|---|---|
| `object` | `Literal["embedding"]` | Fixed value, per OpenAI contract. |
| `embedding` | `list[float]` | Length equals the `dimensions` used for this call (768 by default). |
| `index` | `int` | Position of this vector's corresponding input text in the request. |

**`EmbeddingUsage`**

| Field | Type | Notes |
|---|---|---|
| `prompt_tokens` | `int` | Sum of `tiktoken`-counted tokens across all input texts. |
| `total_tokens` | `int` | Equal to `prompt_tokens` (embeddings have no completion tokens). |

## Internal call shape (`app.core.embedding` / `app.features.embed.service`)

Not a wire contract, but the shape every internal caller (currently just `recommendations/service.py`) depends on and must NOT change:

- `get_embedding_model(dimensions: int | None = None) -> Embeddings` — the shared `langchain_core.embeddings.Embeddings` instance (real or mock). Internally cached (via a private helper) keyed on `(resolved_dimensions, settings.use_mock_llm)` — **not** on `dimensions` alone — so a mock/real mode change is always reflected on the next call, never masked by a stale cache entry (see research.md's amended caching decision). Omitting `dimensions` resolves to `settings.embedding_dimensions` (768).
- `embed_texts(texts: list[str], dimensions: int | None = None) -> list[list[float]]` (`app/features/embed/service.py`) — thin wrapper calling `get_embedding_model(dimensions=dimensions).aembed_documents(texts)`; returns `[]` for an empty input list. The new `dimensions` parameter is additive with a `None` default, so the existing call site in `recommendations/service.py` (`embed_fn([query])`, no `dimensions` arg) is unaffected and keeps getting 768-dim vectors.
