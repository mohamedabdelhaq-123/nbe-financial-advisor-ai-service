# Contract: Embeddings HTTP Endpoint

**Route**: `POST /internal/embeddings`
**Auth**: `Authorization: Bearer <ai_service_token>` (existing `require_token` dependency — 401 on missing/invalid token, same as every other `/internal/*` route)
**Router file**: `app/features/embed/router.py`
**Schemas file**: `app/features/embed/schemas.py`

## Request

`Content-Type: application/json`

```json
{
  "input": ["low-fee savings account", "how do I open a joint account?"],
  "model": "text-embedding-3-small",
  "dimensions": 768
}
```

- `input` (`string | array of strings`, required): text(s) to embed. A single string is accepted and normalized to a one-element list.
- `model` (`string`, optional): accepted for OpenAI-shape compatibility; ignored (this service has a single configured embedding model — see spec Assumptions).
- `dimensions` (`int`, optional): output vector size. Omit to get the default (`settings.embedding_dimensions`, 768 — matches the existing `ai_problem_statements.embedding` column). Pass explicitly for a different size; forwarded to `get_embedding_model(dimensions=...)`.

### Validation errors (`422`)

- `input` missing, an empty array, or an array containing only blank/whitespace strings → rejected with a clear validation error (FR-008).
- `dimensions` present but not a positive integer → rejected with a validation error.

## Response (`200`)

`response_model` is `EmbeddingResponse`, defined locally in `app/features/embed/schemas.py` — a small hand-written Pydantic mirror of OpenAI's documented response fields, not an SDK import (see `research.md` for why: reusing three flat, stable data classes didn't justify taking `openai` on as a project dependency).

```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "embedding": [0.0123, -0.0456, "... 768 floats total ..."],
      "index": 0
    },
    {
      "object": "embedding",
      "embedding": [0.0789, -0.0012, "... 768 floats total ..."],
      "index": 1
    }
  ],
  "model": "text-embedding-3-small",
  "usage": {
    "prompt_tokens": 14,
    "total_tokens": 14
  }
}
```

- `data` is ordered identically to the request's `input` (FR-009); one `EmbeddingDatum` per input text.
- Every `embedding` array is exactly the requested `dimensions` (768 by default) floats long, in both mock and real mode.
- `model` always echoes `settings.embedding_model_name`, regardless of mock/real mode.

## Error responses

| Status | Cause |
|---|---|
| `401` | Missing/invalid Bearer token (`ERROR_RESPONSES`, same as every other internal route). |
| `422` | Request body fails validation (empty/blank `input`, non-positive `dimensions`, wrong types). |
| `502` (or equivalent upstream-failure status) | The real embedding provider is unreachable or returns an error — including an out-of-range `dimensions` value the provider itself rejects (FR-011) — surfaced immediately, no automatic retry. |

## Explicitly out of scope for this contract (see `research.md`)

- `encoding_format: "base64"` (only float arrays are returned).
- Token-array `input` (`Iterable[int]` / `Iterable[Iterable[int]]`) — string input only.
- Selecting between multiple embedding models per request (`model` is accepted but ignored).

## Internal (non-HTTP) contract

For other feature slices inside this service (not the backend):

```python
from app.core.embedding import get_embedding_model

model = get_embedding_model()                    # dimensions defaults to settings.embedding_dimensions (768); mock or real per settings.use_mock_llm, re-checked on every call
vectors = await model.aembed_documents(["some text"])   # list[list[float]], each len == 768

# A caller needing a different dimension overrides it explicitly:
model_1536 = get_embedding_model(dimensions=1536)  # a separately cached (dimensions, mock) build
```

`app/features/embed/service.py`'s existing `embed_texts(texts: list[str]) -> list[list[float]]` keeps its current signature and remains the entry point `recommendations/service.py` already imports — no change required in `recommendations`.
