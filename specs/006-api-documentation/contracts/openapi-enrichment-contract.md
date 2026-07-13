# Contract: Per-endpoint OpenAPI enrichment bar

This is the completeness bar every one of the 9 `/internal/*` endpoints (see
[data-model.md](../data-model.md)) must meet in the generated OpenAPI schema. It exists to give
`/speckit-tasks` a concrete, per-endpoint checklist to turn into tasks, and to give PR
reviewers a concrete checklist for FR-006 (which is enforced by review, not by an automated
test — see research.md §3).

For each of the 9 endpoints, the corresponding OpenAPI `operation` object must have:

1. **`description`** — non-empty, plain-language, sourced from the route function's docstring.
   States what the endpoint does and, where relevant, which upstream/downstream system it talks
   to (e.g. "calls MinerU", "queries pgvector").
2. **`requestBody.content.application/json.schema`** — present for every `POST` endpoint (all 9
   are `POST`), referencing the request Pydantic model, with every field carrying a
   `description` via `Field(description=...)`.
3. **A `responses["200"]`** (or the endpoint's actual success code) **entry with a concrete
   schema** — every endpoint must have an explicit `response_model` (or, for the SSE `/chat`
   endpoint, an explicit `responses={200: {"content": {"text/event-stream": {...}}}}` entry per
   research.md §2) so the success shape is never an untyped `Any`.
4. **A `responses["401"]` entry** — every `/internal/*` endpoint requires the shared Bearer
   token (Constitution II), so every one must document the 401 shape
   (`{"detail": "Invalid or missing token"}`).
5. **A `responses["422"]` entry** — FastAPI already produces this automatically for any typed
   body; this item only requires adding a `responses={422: {...}}` description so it renders
   with an explanation in the docs, not new validation behavior.
6. **At least one example** — either a per-field `examples=[...]` on `Field(...)` or a
   model-level example via `model_config = ConfigDict(json_schema_extra={"examples": [...]})`
   on the request model and on the response model/shape, using synthetic non-PII values only
   (Constitution III).

## Per-endpoint checklist (for `/speckit-tasks` to expand into individual tasks)

| Endpoint | Needs new/updated `response_model`? | Needs docstring added? |
|---|---|---|
| `POST /internal/chat` | N/A (SSE — use `responses=` per research.md §2) | Yes |
| `POST /internal/analyze/post-ingestion` | Yes — no model exists for its `dict` shape today | Yes |
| `POST /internal/analyze/monthly-summary` | Yes — currently returns `.model_dump()` untyped | Yes |
| `POST /internal/analyze/anomaly-check` | Yes — currently returns `list[dict]` untyped | Yes |
| `POST /internal/plan/question` | Yes — currently returns a raw dict, no model | Yes |
| `POST /internal/plan/generate` | No (has `GeneratePlanResponse`) — add field descriptions/examples | Yes |
| `POST /internal/ingestion/process` | No (has `ProcessStatementResult`) — add field descriptions/examples | No (already documented) |
| `POST /internal/ingestion/normalize` | No (has `NormalizeStatementResult`) — add field descriptions/examples | No (already documented) |
| `POST /internal/recommendations/match` | No (has `MatchResponse`) — add field descriptions/examples | Yes |

Every row also needs: request-model field descriptions/examples (all 9), and `responses={401:
..., 422: ...}` added at the router level (can be applied once per router via a shared
constant, since the 401/422 shapes are identical across every `/internal/*` endpoint).
