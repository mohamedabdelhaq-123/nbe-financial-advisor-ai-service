# Research: API Documentation

All items in Technical Context were resolvable without `NEEDS CLARIFICATION` — the scope
ambiguities were already resolved during `/speckit-clarify`. This document records the
technical approach decisions needed to execute Phase 1 design.

## 1. Adding descriptions, examples, and error responses to existing endpoints

**Decision**: Use FastAPI/Pydantic v2 native mechanisms exclusively:
- Endpoint purpose description → the route function's docstring (FastAPI renders it as the
  operation description automatically — `ingestion/router.py` already does this; the pattern
  extends to `chat`, `analytics`, `plan`, `recommendations`).
- Request/response field descriptions and examples → `pydantic.Field(description=...)` on each
  model field, plus `model_config = ConfigDict(json_schema_extra={"examples": [...]})` on each
  request/response model for a full-payload example (Pydantic v2's supported mechanism, renders
  natively in Swagger UI's "Example Value" panel).
- Success response shape → add an explicit `response_model` to every route that's currently
  missing one (`chat`, `analytics`'s three routes, `plan`'s two routes) so the schema shows a
  concrete shape instead of an untyped `Any`.
- Error responses → the `responses={401: {...}, 422: {...}}` parameter on `@router.post(...)`,
  populated once per router via a shared `ERROR_RESPONSES` constant in `app/core/security.py`
  (401 body matches `HTTPException(status_code=401, detail=...)`'s shape; 422 is FastAPI's
  built-in validation-error shape, already produced automatically for every endpoint with a
  Pydantic body).

**Rationale**: All of this is FastAPI/Pydantic's native, already-dependency-present mechanism —
no new library, no hand-rolled schema post-processing (Constitution VIII). None of it changes
what a route requires to be called or what `/docs`/`/redoc`/`/openapi.json` require to be
viewed — it only adds descriptive metadata to routes and schemas that already exist.

**Alternatives considered**:
- *A hand-written OpenAPI YAML/JSON overlay merged at startup* — rejected: duplicates
  information already expressible on the models/routes themselves, and is exactly the kind of
  parallel-format duplication Constitution VIII warns against; it would also drift from the real
  models (violates US2/FR-005).
- *A docstring-only approach with no `Field`/`response_model` changes* — rejected: doesn't
  satisfy FR-002/FR-003 (error shapes, request/response field-level detail), and several
  endpoints (`chat`, three `analytics` routes, two `plan` routes) currently have no
  `response_model` at all, so their success shape wouldn't appear in the schema either.

## 2. Documenting the SSE chat endpoint

**Decision**: `POST /internal/chat` keeps its `StreamingResponse` return type (OpenAPI has no
native SSE construct), but its docstring explicitly states the response is
`text/event-stream` and describes the event payload shape in prose, and the route sets
`responses={200: {"content": {"text/event-stream": {"schema": {...}}}, "description": ...}}`
so the one documented example event shape is visible in the schema even though Swagger UI's
"try it out" will only show the raw stream, not a parsed event list.

**Rationale**: Satisfies FR-004/edge-case coverage using only what FastAPI's `responses=`
parameter already supports — no SSE-specific OpenAPI extension library needed.

**Alternatives considered**: A dedicated AsyncAPI spec for the stream — rejected as
disproportionate for one endpoint and outside this feature's confirmed scope (Assumptions:
delivery mechanism is the existing OpenAPI/Swagger/ReDoc stack, not a second spec format).

## 3. Testing scope: no new tests needed

**Decision**: This feature adds no new runtime behavior — only descriptions, examples, and
typed response models on routes that already exist and already require the same
`require_token` dependency they always have. The existing test suite (in particular
`tests/features/test_auth_matrix.py`, which is unaffected by this feature) continues to verify
the real behavior; no new test file is added.

Deliberately **not** added: any test that asserts every endpoint/field has a description or
example. Constitution I makes the whole pytest suite a hard CI merge gate, so any such test
would silently convert FR-006's clarified answer (Option B — "manual PR review only, no
automated check") into an automated gate by the back door. Since `/speckit-clarify` recorded an
explicit choice against that, this feature must not introduce one, even informally.

**Rationale**: Keeps the test suite verifying only what the spec actually requires to be
enforced automatically, while leaving documentation completeness exactly where the clarified
answer placed it — a PR-review responsibility, not a CI gate.

**Alternatives considered**: A "completeness" test suite — rejected per the reasoning above: it
would contradict the explicit clarification answer rather than merely being extra rigor.
