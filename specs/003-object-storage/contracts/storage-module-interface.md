# Contract: `app/core/storage.py` internal interface

This feature exposes no HTTP endpoints (FR-011) — its only "interface to
other systems" is the Python interface other in-process code (feature
routers, services, background jobs, agent/graph nodes) programs against.
This document pins that contract down so consumers across feature slices
rely on the same shape.

## `get_storage_backend()`

```python
def get_storage_backend() -> AsyncContextManager["S3Client"]:
    ...
```

- **Returns**: a fresh, **unentered** aioboto3 S3 client context manager,
  configured from current `Settings` (`storage_s3_endpoint_url`,
  `storage_s3_region`, `storage_s3_access_key`, `storage_s3_secret_key`,
  `storage_s3_use_path_style`).
- **Usage contract**: callers MUST enter it via `async with`:
  ```python
  async with get_storage_backend() as s3:
      await s3.put_object(Bucket=settings.storage_s3_bucket, Key=key, Body=data)
  ```
- **Guarantees**:
  - Safe to call from any async context — router handlers, background
    jobs, LangGraph nodes — with no dependency on an active HTTP request
    (FR-010). Not registered as a FastAPI `Depends`; import and call
    directly.
  - A new client is opened per call; this module holds no long-lived
    connection across calls, so there is no cross-request state to leak
    or exhaust.
  - Does not perform any network call itself — connecting happens when
    the returned context manager is entered and an operation is issued
    against it.
- **Non-guarantees / caller responsibilities**:
  - Does not validate `key` — callers MUST call `validate_storage_key(key)`
    first for any key influenced by external/user input.
  - Does not create the bucket if missing (FR-009) — a missing bucket
    surfaces as a normal S3 error (e.g. `NoSuchBucket`) from whichever
    operation the caller issues.
  - Does not interpret, minimize, or redact the bytes it's given — PII
    handling is the calling feature's responsibility (Constitution
    Principle III), enforced at the point the caller decides what to
    write.

## `validate_storage_key(key: str) -> None`

```python
def validate_storage_key(key: str) -> None:
    ...
```

- **Input**: `key` — a logical, path-like string identifying an object
  within the configured bucket (e.g. `"chat/attachments/<id>.pdf"`).
- **Behavior**: raises `ValueError` if `key`:
  - is not equal to its own `posixpath.normpath` result, or
  - starts with `/` (absolute path), or
  - would resolve outside its own namespace via a leading `..` segment.
- **Guarantee**: when this function does not raise, no S3 operation
  performed with `key` can escape the configured bucket's logical
  namespace (FR-007, SC-004). This check happens entirely in-process —
  it makes no network call, so rejection is immediate regardless of
  object-store reachability.
- **Caller contract**: MUST be called before using any key built from
  data outside the calling feature's own control (e.g. a user-supplied
  filename) as an S3 `Key`. Features SHOULD additionally slugify or
  UUID-suffix user-supplied filename components rather than relying on
  this check as the sole defense (defense in depth, not a substitute for
  input hygiene at the feature layer).

## Error surface

This module introduces no custom exception types. Callers should expect
and handle:
- `ValueError` from `validate_storage_key` (invalid key).
- `botocore.exceptions.ClientError` (and subclasses) from S3 operations
  issued against the client `get_storage_backend()` returns — e.g.
  `NoSuchBucket`, `NoSuchKey`/404 on a missing object via `get_object` or
  `head_object`, connection/timeout errors if the configured endpoint is
  unreachable.
- `RuntimeError` at service **startup** (not at call time) if required
  storage settings are incomplete (FR-008) — this surfaces from
  `app/core/config.py` import, before any code using this module can run.

## What is explicitly out of contract (deferred)

- Presigned URL generation (no direct-to-client download URLs in this
  version — see spec.md Assumptions).
- Streaming/chunked upload-download helpers for very large blobs (no
  opinion enforced; callers may use the returned client's own streaming
  facilities, e.g. reading `get_object`'s `Body` incrementally, if a
  future need arises).
- Any HTTP-facing upload/download route (FR-011).
