# Contract: async ingestion jobs

Three new routes. **Additive only** — `POST /internal/ingestion/process` and `POST
/internal/ingestion/normalize` keep their current paths, request shapes, response shapes, and
blocking behavior (FR-014). Field-level details are in [data-model.md](../data-model.md).

Submission stays on the ingestion router (`POST /internal/ingestion/jobs/process` and
`.../jobs/normalize`), since only ingestion knows what a "target" means for its own jobs. Reading a
job's status back is generic and lives on a shared route, `GET /internal/tasks/{job_id}`, that
every feature's async jobs are read through — not ingestion-prefixed, because nothing about a
status read is ingestion-specific.

All three inherit `Depends(require_token)`, so the auth and `401` behavior is identical to every
other `/internal/*` route (FR-013).

**`job_id` is SAQ's job key** — an opaque string, not a UUID the caller should parse. Treat it as
`str` and echo it back unmodified. The four states in this contract are derived from SAQ's status
plus the job's result envelope; see [data-model.md](../data-model.md) for the mapping.

## `POST /internal/ingestion/jobs/process`

Submits extraction for a previously uploaded statement.

```
POST /internal/ingestion/jobs/process
Authorization: Bearer <AI_SERVICE_TOKEN>
Content-Type: application/json
```

```json
{ "statement_id": "b3f1c2d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d" }
```

Request body is `ProcessStatementRequest` — unchanged from the blocking endpoint.

### `202 Accepted`

```json
{
  "job_id": "7f1a9c30-2b44-4d51-9a2e-6c8b0f3d1e77",
  "step": "process",
  "state": "queued",
  "submitted_at": "2026-07-28T09:14:03.221Z"
}
```

Returned well before the extraction itself finishes (SC-001: under 2s for 95% of submissions). The
job's state is readable at `GET /internal/tasks/{job_id}` immediately — the row is committed before
this response is written, so there is no window where a just-issued reference reads as unknown.

A repeat submission for a statement that already has a `queued` or `running` extraction job returns
`202` with **that job's** `job_id`, `state`, and original `submitted_at` — no second execution starts
(FR-010). Once the previous job is terminal, the same request creates a new job instead (FR-011).

### `404 Not Found`

```json
{ "detail": "statement not found" }
```

The statement does not exist. No job record is created (FR-003). Same detail string the blocking
endpoint returns for the same condition.

### `401`, `422`

As documented by `ERROR_RESPONSES` for every `/internal/*` route.

## `POST /internal/ingestion/jobs/normalize`

Submits normalization for a previously extracted statement.

```json
{ "ocr_result_id": "c4d5e6f7-8a9b-0c1d-2e3f-4a5b6c7d8e9f" }
```

Request body is `NormalizeStatementRequest` — unchanged from the blocking endpoint.

### `202 Accepted`

Same shape as above with `"step": "normalize"`. Same dedup behavior, scoped to the normalization step
for that OCR result — an in-flight extraction job never suppresses a normalization submission, and
vice versa.

### `404 Not Found`

```json
{ "detail": "ocr result not found" }
```

## `GET /internal/tasks/{job_id}`

Reads a job's current state. Repeatable and non-destructive: reading a result never consumes or
alters it, and a terminal state never changes afterwards (FR-008).

Generic across every feature's async jobs — the `function` field (SAQ's registered job-function
name, e.g. `"ingestion.process"` / `"ingestion.normalize"`) identifies what kind of work a given
job is; there is no `step` or `target_id` field, since those are ingestion-specific concepts a
shared route has no business encoding. A caller that only ever submits through ingestion's
`/jobs/*` routes already knows the target from its own submission call.

### `200 OK` — queued

```json
{
  "job_id": "7f1a9c30-2b44-4d51-9a2e-6c8b0f3d1e77",
  "function": "ingestion.process",
  "state": "queued",
  "submitted_at": "2026-07-28T09:14:03.221Z",
  "started_at": null,
  "finished_at": null,
  "result": null,
  "error": null
}
```

### `200 OK` — running

As above with `"state": "running"` and `started_at` set. `result` and `error` stay null.

### `200 OK` — succeeded (`ingestion.process`)

```json
{
  "job_id": "7f1a9c30-2b44-4d51-9a2e-6c8b0f3d1e77",
  "function": "ingestion.process",
  "state": "succeeded",
  "submitted_at": "2026-07-28T09:14:03.221Z",
  "started_at": "2026-07-28T09:14:03.402Z",
  "finished_at": "2026-07-28T09:21:47.918Z",
  "result": {
    "prefix": "pfm-statements-ocr/b3f1c2d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d/",
    "ocr_engine": "MinerU",
    "confidence_score": 1.0
  },
  "error": null
}
```

`result` is exactly the body `POST /internal/ingestion/process` returns for the same input (FR-006).

### `200 OK` — succeeded (`ingestion.normalize`)

```json
{
  "job_id": "a2c81f55-9d0e-4a17-b3f0-51ce7d9a4402",
  "function": "ingestion.normalize",
  "state": "succeeded",
  "submitted_at": "2026-07-28T09:22:10.004Z",
  "started_at": "2026-07-28T09:22:10.140Z",
  "finished_at": "2026-07-28T09:26:55.771Z",
  "result": {
    "normalized_json": {
      "bank_name": "National Bank of Egypt",
      "account_number": "4213010248203200016",
      "transactions": [
        {
          "transaction_date": "2026-05-01",
          "merchant_raw": "Carrefour #abc123",
          "merchant_normalized": "Carrefour",
          "ai_description": "A grocery purchase at a Carrefour supermarket.",
          "category": "food",
          "amount": 1234.56,
          "transaction_type": "debit",
          "balance": 4809.31,
          "duplicate_of": null
        }
      ]
    },
    "model_used": "gpt-4o-mini"
  },
  "error": null
}
```

Exactly the body `POST /internal/ingestion/normalize` returns for the same input — see
[spec 016's contract](../../016-normalizer-pipeline-rework/contracts/ingestion-normalize.md) for the
full `normalized_json` shape, which this feature does not change.

This payload is the durable second copy of full transaction detail and the unmasked account number
that FR-006a governs: reachable only here, with a valid token; never logged or exported to telemetry;
deleted 30 days after `finished_at`.

### `200 OK` — failed

```json
{
  "job_id": "a2c81f55-9d0e-4a17-b3f0-51ce7d9a4402",
  "function": "ingestion.normalize",
  "state": "failed",
  "submitted_at": "2026-07-28T09:22:10.004Z",
  "started_at": "2026-07-28T09:22:10.140Z",
  "finished_at": "2026-07-28T09:22:41.006Z",
  "result": null,
  "error": "normalization engine failed: connection refused"
}
```

`error` preserves the diagnostic detail the blocking endpoint puts in its `502` `detail` for the same
failure (FR-007) — `"failed to retrieve source document: …"`, `"document processing engine failed:
…"`, `"failed to retrieve OCR content: …"`, `"failed to parse OCR content: …"`, `"normalization
engine failed: …"`, `"statement not found"` / `"ocr result not found"` when the target was deleted
between submission and execution.

A job that was **executing** when the service died is swept to `failed` with an interrupted reason
and is not re-executed. A job that was still **queued** at that moment is *not* failed — it resumes
when the worker restarts and runs to completion normally (FR-009 as amended).

An unexpected internal error yields `failed` with a generic message — stack traces stay in the
service logs and are never returned to the caller.

**Note that a failed job is still `200`, not an error status.** The read succeeded; the job is what
failed. Only an unknown reference is a `404`.

### `404 Not Found`

```json
{ "detail": "job not found" }
```

Unknown reference, or a job whose record has aged out under the 30-day `ttl` — the caller cannot
distinguish the two, by design.

## Not in this contract

- **No callbacks.** The caller polls; this service never initiates traffic toward the backend.
- **No cancellation.** There is no `DELETE`.
- **No listing.** No route enumerates jobs; a caller reads only references it holds.
- **No progress detail.** `state` is coarse — no queue position, no percentage.
