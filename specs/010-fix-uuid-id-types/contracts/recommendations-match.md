# Contract: POST /internal/recommendations/match

**Feature**: [../spec.md](../spec.md) | **Auth**: Bearer token (`require_token`, same as every `/internal/*` route) | **Status**: newly documented (the endpoint predates this feature; its contract was implicit).

## Summary

The standalone recommendation match endpoint takes a natural-language query and returns the top-K matching products from this service's own `ai_problem_statements` table (vector similarity), enriching each match with the real product title from the backend `Products` table. This feature fixes the `user_id` and `product_id` types to UUID (they were previously `int`, contradicting the backend's UUID ground truth) and writes the contract down for the first time.

## Request

```json
{
  "user_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
  "query": "low-fee savings account",
  "top_k": 3
}
```

| Field | Type | Default | Rule |
|---|---|---|---|
| `user_id` | `UUID4` | (required) | Backend user ID the match is being shown to. Used to attribute the recommendation-log row; MUST be a valid UUID. |
| `query` | `str` | (required) | Natural-language description of what the user is looking for. Empty/whitespace string returns an empty matches list (no error). |
| `top_k` | `int` | `3` | Maximum number of matches to return. Must be `≤ 3` (enforced by Pydantic `le=3`); the bound matches the chat agent's own `top_k=3` and bounds the backend `Products` title-lookup cost (`plan.md`). |

**Breaking change vs. prior behavior**: `user_id` was previously `int`. Callers that sent integers (e.g. `1001`) will now receive a 422 validation error — this is the intended fail-fast signal (Constitution Principle VII).

## Response `200`

```json
{
  "matches": [
    {
      "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
      "product_name": "Premium Savings Account",
      "similarity": 0.87
    }
  ]
}
```

| Field | Type | Rule |
|---|---|---|
| `matches` | `list[ProductMatch]` | Ranked by descending similarity. Possibly empty. |
| `matches[].product_id` | `UUID4` | Backend `Products.id`. The same UUID the backend uses to identify the product. |
| `matches[].product_name` | `str` | Real product title, fetched from the backend `Products` table (read-only). Replaces the prior fabricated `"Product {id}"` placeholder. |
| `matches[].similarity` | `float` | Cosine similarity score in `[0.0, 1.0]`. Matches below the service's `SIMILARITY_THRESHOLD = 0.5` are filtered out before the response is built. |

**Breaking change vs. prior behavior**: `product_id` was previously `int`. Callers that parsed it as an integer must now parse it as a UUID string.

## Response outside 200

- **401** — missing/invalid Bearer token. Standard `ERROR_RESPONSES[401]` shape; nothing is processed.
- **422** — request body failed Pydantic validation. This is the new fail-fast behavior for callers sending non-UUID `user_id`.

## Side effects on success

- For each match returned, exactly one row is inserted into the own-DB `ai_recommendation_logs` table, with `user_id` (UUID), `product_id` (UUID), `matched_query`, `similarity_score`, and `shown_at`. This is unchanged in shape from before; only the column types changed (see parent feature `data-model.md`).
- No write to any backend table (Constitution Principle IV — read-only by default).

## Backend outage behavior

If the backend `Products` table is unreachable at match time, the endpoint degrades gracefully: matches are still returned, with `product_name` falling back to a placeholder (e.g. `"Product unavailable"`). The recommendation log still records the match. The endpoint does not raise 5xx on a backend outage — matches the graceful-degradation pattern the analysis agent already uses (`chat/agents/analysis.py:74`). The exact fallback string is a small implementation choice left to `tasks.md`.

## Caller inventory

- The chat widget flow (`chat/agents/recommendation.py`) calls `match()` directly — gets UUID-typed results, drops its `str()` bridging cast.
- The standalone `/internal/recommendations/match` endpoint is the only other caller. It is invoked by the Django backend for any non-chat product-search surface.

There are no external third-party callers of this internal service.

## Cross-reference

- Parent feature: [../spec.md](../spec.md)
- Data model: [../data-model.md](../data-model.md)
- Chat-stream widget payload amendment (related): [chat-stream-amendment.md](chat-stream-amendment.md)
