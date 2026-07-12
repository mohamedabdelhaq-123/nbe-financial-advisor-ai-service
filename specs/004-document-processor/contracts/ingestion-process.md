# Contract: `POST /internal/ingestion/process`

Internal endpoint, called only by the Django backend. Requires the same shared-secret Bearer token
as every other internal route (`require_token`).

## Request

```
POST /internal/ingestion/process
Authorization: Bearer <AI_SERVICE_TOKEN>
Content-Type: application/json
```

```json
{
  "statement_id": "3f8a1c2e-....-uuid"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `statement_id` | string (UUID) | yes | Must reference an existing `statement_files` row |

## Response — success (200)

```json
{
  "prefix": "pfm-statements-ocr/3f8a1c2e-....-uuid/",
  "ocr_engine": "MinerU"
}
```

| Field | Type | Notes |
|---|---|---|
| `prefix` | string | `"{bucket}/{statement_id}/"` — same `"{bucket}/{path}"` shape as `StatementFiles.seaweed_file_id`, so the backend can store/consume it the same way. Objects under this prefix: `markdown.md`, `content_list.json`, `images/<name>` (zero or more). |
| `ocr_engine` | string | Always the fixed literal `"MinerU"` in this version. |

## Response — failure

| Status | Condition | Body shape |
|---|---|---|
| `422` | `statement_id` is not a valid UUID | `{"detail": [...]}` (standard FastAPI/Pydantic validation error — the request schema types `statement_id` as a UUID, so malformed input never reaches application code) |
| `401` | Missing/invalid Bearer token | `{"detail": "Invalid or missing token"}` (existing `require_token` behavior) |
| `404` | `statement_id` does not match any known statement | `{"detail": "statement not found"}` |
| `502` | Source document could not be retrieved from storage, **or** MinerU was unreachable/timed out/returned an unusable result | `{"detail": "..."}` — message distinguishes which side failed (source-storage vs. processing-engine) per spec edge cases |

No other status codes are part of this contract. There is no partial-success shape — a request
either returns the full `prefix`/`ocr_engine` body or an error; nothing is persisted to the
response bucket for a request that ultimately fails (best-effort: a failure after the last
artifact write, e.g. during the audit-log write, is a pre-existing class of problem shared with
every other write-then-audit endpoint in this service, not something this feature introduces new
handling for).

## What this endpoint explicitly does NOT do

- Does not accept or return raw file bytes — only a reference in, a location out.
- Does not return extracted content inline (no `markdown`/`content_list` field in the response
  body) — the caller fetches artifacts from `prefix` itself if/when it needs the bytes.
- Does not perform normalization/column-mapping into transactions.
- Does not write to any backend-owned table (`statement_ocr_results` or otherwise) — the backend
  persists that itself using this response.
