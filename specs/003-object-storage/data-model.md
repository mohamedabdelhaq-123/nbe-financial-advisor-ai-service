# Phase 1 Data Model: Object Storage Infrastructure

This feature introduces no relational schema — no Alembic migration, no
SQLAlchemy model, no change to either the own DB or the backend DB. The
only "data model" is the shape of the blob store itself and its
configuration.

## Entity: Stored Object

Represents one binary payload held in the configured S3-compatible bucket.

| Field   | Type    | Description |
|---------|---------|--------------|
| `key`   | string  | Logical, path-like identifier (e.g. `"chat/attachments/<id>.pdf"`). Scoped within exactly one configured bucket. |
| `bytes` | bytes   | The stored payload, opaque to this module — no interpretation, no metadata extraction. |

**Validation rules**:
- `key` MUST equal its own `posixpath.normpath` result, MUST NOT start
  with `/`, and MUST NOT resolve to a path outside its own namespace via
  `..` segments (FR-007). Enforced by `validate_storage_key()` before any
  operation reaches the network.
- No constraint on `bytes` content or size is enforced by this module
  (Assumption: blobs are moderate-sized; see spec.md Assumptions).

**Lifecycle**: Objects only have two states from this module's point of
view — present (written, not yet deleted) or absent (never written, or
deleted). No versioning, no soft-delete, no expiry is introduced by this
feature.

**Relationships**: None at this layer. Any association between a Stored
Object's key and a business entity (a chat message, a user, an analytics
report) is owned and tracked by whichever feature slice writes that key —
this module has no foreign-key-like concept linking a key back to owning
data.

## Configuration Entity: Storage Settings

Not a database entity — new fields on the existing `Settings`
(`app/core/config.py`) singleton, validated at import time.

| Field                        | Type | Required | Notes |
|------------------------------|------|----------|-------|
| `storage_s3_bucket`          | str  | Yes (fail-fast) | Target bucket name; must already exist (FR-009). |
| `storage_s3_endpoint_url`    | str  | No (blank = real AWS S3) | Set for SeaweedFS or any other S3-compatible endpoint. |
| `storage_s3_region`          | str  | No (default `us-east-1`) | Passed through to the client regardless of provider. |
| `storage_s3_access_key`      | str  | Yes (fail-fast) | Never committed; supplied via `.env`/environment. |
| `storage_s3_secret_key`      | str  | Yes (fail-fast) | Never committed; supplied via `.env`/environment. |
| `storage_s3_use_path_style`  | bool | No (default `True`) | SeaweedFS and most self-hosted S3-compatible providers require path-style addressing. |

**Validation rule**: at import time, if `storage_s3_bucket`,
`storage_s3_access_key`, or `storage_s3_secret_key` is missing, raise
`RuntimeError` immediately (FR-008) — mirrors the existing
`openai_api_key`/`ai_service_token` fail-fast checks in `config.py`. No
live connection or bucket-existence check is performed at import time
(stays offline, per Constitution Principle VII and the existing
`backend_db_host` precedent).
