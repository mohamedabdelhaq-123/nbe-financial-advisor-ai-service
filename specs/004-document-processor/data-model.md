# Data Model: Statement Document Processor

This feature introduces **no new database tables and no schema migration**. It reads one existing
backend-owned model and writes one row to one existing own-DB model. Everything else it handles is
in-memory or object-storage bytes, not relational data.

## Entities read

### `StatementFiles` (existing, `app/backend_db/models/statements.py`, read-only)

The only backend-owned row this feature reads. Relevant columns:

| Column | Type | Used for |
|---|---|---|
| `id` | UUID | Looked up by the caller-supplied `statement_id` |
| `seaweed_file_id` | `str` | Split into `(source_bucket, source_key)` to fetch the raw document |

No other column is read. No column of this model, or any other backend-owned model, is ever
written by this feature (Constitution IV; spec SC-005).

## Entities written

### `AiAuditLog` (existing, `app/features/audit/models.py`, own DB, already migrated)

One row is inserted per processing call, via the existing `app.core.audit.record_audit()` helper
(already used by `chat/service.py`) plus an explicit `session.commit()` at the call site, since
`record_audit()` itself only flushes:

| Column | Value this feature supplies |
|---|---|
| `user_id` | `None` (this capability has no authenticated end-user context — the caller is the backend, not a specific user) |
| `action` | `"ingestion.process"` |
| `detail_json` | JSON string: `{"statement_id": <str>, "prefix": <str>}` |
| `created_at` | Set by the model's default (`datetime.utcnow`) |

No new migration is required — the table already exists via
`migrations/versions/a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py`.

## Non-relational data this feature handles

These are not persisted as rows anywhere; they only exist as object-storage blobs and in-memory
values during one request:

| Conceptual entity | Representation | Where it lives |
|---|---|---|
| **Source document bytes** | Raw PDF bytes | Fetched from `{source_bucket}/{source_key}` (parsed from `seaweed_file_id`), never persisted again by this feature |
| **Extracted markdown** | UTF-8 text | Written to `{settings.storage_s3_ocr_bucket}/{statement_id}/markdown.md` |
| **Extracted content list** | JSON bytes | Written to `{settings.storage_s3_ocr_bucket}/{statement_id}/content_list.json` |
| **Extracted images** | Binary (per original format) | Written to `{settings.storage_s3_ocr_bucket}/{statement_id}/images/<original-name>` |
| **Processing result** | `ProcessStatementResult` (Pydantic, response only) | Returned to the caller, not persisted by this service |

## Validation rules

- `statement_id` (request input) MUST parse as a UUID; a non-UUID value is a client error (422,
  enforced by typing the request field as `UUID` rather than `str`), distinct from a
  well-formed-but-unknown UUID (404 — FR-006).
- `seaweed_file_id` MUST contain at least one `/` before being split into bucket/key; a value that
  doesn't is treated as a source-retrieval failure (FR-007), since it cannot address any object.
- No `validate_storage_key()` call is required for `source_key` — it comes from a trusted backend
  DB row, not from external/caller-supplied input, which is the trust tier that guard is meant for
  (`specs/003-object-storage/contracts/storage-module-interface.md`). The *write*-side keys this
  feature constructs itself (`{statement_id}/...`) are derived from a UUID already validated above,
  so they cannot contain path-traversal segments.

## State / lifecycle

There is no multi-step state machine — one processing request is a single, synchronous,
all-or-nothing operation from the caller's point of view: it either returns a complete
`ProcessStatementResult` (all three artifact kinds persisted, one audit row written) or it returns
an explicit failure and persists nothing new. Re-processing the same `statement_id` overwrites the
three objects at its existing prefix (spec Assumptions — no versioning in v1).
