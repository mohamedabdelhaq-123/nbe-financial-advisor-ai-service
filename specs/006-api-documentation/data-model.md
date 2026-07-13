# Data Model: API Documentation

This feature introduces no new persisted entities and no new database tables (Constitution IV
is not implicated). "Data model" here means the **documentation-facing entities**: the existing
request/response Pydantic models this feature must annotate, and the endpoint inventory that
must reach full documentation coverage (spec.md SC-001/SC-002).

## Endpoint inventory (documentation scope)

| Method | Path | Feature slice | Current `response_model`? | Docstring today? |
|---|---|---|---|---|
| POST | `/internal/chat` | chat | No (SSE `StreamingResponse`) | No |
| POST | `/internal/analyze/post-ingestion` | analytics | No (`dict`) | No |
| POST | `/internal/analyze/monthly-summary` | analytics | No (`.model_dump()`) | No |
| POST | `/internal/analyze/anomaly-check` | analytics | No (`list[dict]`) | No |
| POST | `/internal/plan/question` | plan | No (raw dict) | No |
| POST | `/internal/plan/generate` | plan | Yes (`GeneratePlanResponse`, unannotated) | No |
| POST | `/internal/ingestion/process` | ingestion | Yes (`ProcessStatementResult`) | Yes |
| POST | `/internal/ingestion/normalize` | ingestion | Yes (`NormalizeStatementResult`) | Yes |
| POST | `/internal/recommendations/match` | recommendations | Yes (`MatchResponse`, unannotated) | No |
| GET | `/health` | core (system) | N/A (public probe) | N/A |
| GET | `/ready` | core (system) | N/A (public probe) | N/A |

9 `/internal/*` endpoints require full enrichment (description + request/response shape +
error responses + example) per SC-001/SC-002. `/health`, `/ready`, `/docs`, `/redoc`, and
`/openapi.json` are unchanged by this feature — their access posture stays exactly as it is
today (see spec.md Assumptions).

## Request/response models requiring `Field(description=..., examples=...)` and a model-level example

### chat (`app/features/chat/schemas.py`)
- `ChatTurnRequest`: `conversation_id`, `user_id`, `message`, `is_first_turn`, `initial_context`, `refresh_context`
- No response model exists (SSE stream) — documented via `responses=` per research.md §2, not a schema class

### analytics (`app/features/analytics/schemas.py`)
- `MonthlySummaryRequest` / `AnomalyCheckRequest` / `PostIngestionRequest`: `user_id`, `account_id`, `month`
- `MonthlySummaryResult`: `user_id`, `account_id`, `month`, `total_income`, `total_expense`, `net`, `by_category`, `embedding`
- `AnomalyFlagResult`: `user_id`, `account_id`, `category`, `month`, `amount`, `reason`
- `RecurringChargeResult`: exists but is currently unused by any route response — out of scope (no endpoint to attach it to)
- `/post-ingestion`'s actual return shape (`{"summary": ..., "recurring_charges": [...], "anomalies": [...]}`) has no matching Pydantic model today — this feature must either add one (e.g. `PostIngestionResult`) or set an explicit `response_model` composing the existing result models, so the endpoint's success shape is documented at all (currently untyped `dict`)

### plan (`app/features/plan/schemas.py`)
- `NextQuestionRequest`: `user_context`, `answers`, `questions_asked`
- `GeneratePlanRequest`: `user_context`, `answers`
- `PlanQuestion`: `id`, `text` — returned today as a raw `{"question": ...}` dict, not via `response_model`; this feature must add a response model (e.g. `NextQuestionResponse{question: PlanQuestion | None}`) so `/plan/question`'s shape is documented
- `GeneratePlanResponse`: `allocations: list[BudgetAllocation]`; `BudgetAllocation`: `category`, `percentage`

### ingestion (`app/features/ingestion/schemas.py`)
- `ProcessStatementRequest`: `statement_id`
- `ProcessStatementResult`: `prefix`, `ocr_engine`
- `NormalizeStatementRequest`: `ocr_result_id`
- `NormalizeStatementResult`: `normalized_json`, `model_used`

### recommendations (`app/features/recommendations/schemas.py`)
- `MatchRequest`: `user_id`, `query`, `top_k`
- `ProductMatch`: `product_id`, `product_name`, `similarity`
- `MatchResponse`: `matches: list[ProductMatch]`

## Shared error response shapes (documented once per router via `responses=`)

- **401 Unauthorized** — produced by `require_token` (`app/core/security.py`): `{"detail": "Invalid or missing token"}`
- **422 Unprocessable Entity** — FastAPI's built-in Pydantic validation error shape (already generated automatically for any endpoint with a typed body; only needs a `responses={422: {...}}` entry added for it to render a description in the docs, not new behavior)

No new entities, no state transitions, no lifecycle rules — this feature only adds descriptive
metadata to fields/models/routes that already exist.
