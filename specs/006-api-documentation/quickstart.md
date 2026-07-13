# Quickstart: Validating API Documentation

Prerequisites: repo checked out on `006-api-documentation` (or the branch implementing it),
dependencies installed via `uv sync`, and `AI_SERVICE_TOKEN` set in `.env`/environment (the app
fails fast at import if it's missing — see `app/core/config.py`).

## 1. Run the service locally

```bash
uv run uvicorn app.main:app --reload
```

## 2. Validate US1 — every `/internal/*` endpoint is self-explanatory from the docs (SC-001, SC-002, SC-003)

1. Open `http://localhost:8000/docs` in a browser.
2. Click the "Authorize" button and paste the `AI_SERVICE_TOKEN` value (needed to exercise any
   "try it out" call, exactly as before this feature — this feature does not change that
   requirement).
3. For each of the 9 `/internal/*` operations listed in
   [data-model.md](data-model.md#endpoint-inventory-documentation-scope), confirm:
   - A plain-language description is visible under the operation.
   - The request body schema shows every field with a description, and an example payload is
     pre-filled in "Try it out".
   - The "Responses" panel lists `200` (or the endpoint's real success code), `401`, and `422`,
     each with a schema and example.
4. Time how long it takes to determine the correct request shape for one endpoint you haven't
   looked at before — this should take under 5 minutes (SC-003).

## 3. Validate the SSE endpoint is documented despite not being "try it out"-able (FR-004)

1. On `/docs`, open `POST /internal/chat`.
2. Confirm the description states the response is a `text/event-stream` and describes the
   event shape in prose (per research.md §2) — "try it out" is expected to only show a raw
   stream, not a parsed event list, and that's fine.

## 4. Run the existing test suite

```bash
uv run pytest
```

Expected: all pass, unchanged. This feature adds no new tests (research.md §3) — it only adds
descriptive metadata to routes/schemas the existing suite already exercises. Documentation
completeness is a manual PR-review responsibility per the clarified spec decision (FR-006); use
[contracts/openapi-enrichment-contract.md](contracts/openapi-enrichment-contract.md) as the
review checklist for that.
