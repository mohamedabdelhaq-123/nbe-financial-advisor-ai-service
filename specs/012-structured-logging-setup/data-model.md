# Phase 1 Data Model: Structured Logging Setup

This feature introduces no persisted storage (no new database tables — see
Technical Context: Storage = N/A). The one entity from the spec's Key
Entities section is a per-line, in-flight shape, not a stored record: it
exists only as the structured payload written to stdout for the lifetime of
that log call.

## Log Entry

Represents a single emitted structured log line.

| Field | Type | Required | Notes |
|---|---|---|---|
| `timestamp` | ISO-8601 string (UTC) | always | Set by the logging setup itself, never passed by call sites (FR-003) |
| `level` | enum: `debug` \| `info` \| `warning` \| `error` \| `critical` | always | Maps to Python stdlib severity levels (FR-002, FR-003) |
| `logger` | string | always | Originating module/feature, derived from `get_logger(__name__)` (FR-003, FR-008) |
| `event` | string | always | Human-readable message (FR-003) |
| `correlation_id` | UUID string | always when inside a request/job scope | Bound once per request via middleware/contextvars; absent only for logging that occurs before any request scope exists (e.g. very early startup) (FR-004) |
| `exception` | object: `{type, message, stacktrace}` | only on error paths | Populated by `logger.exception(...)` / error-level calls with an active exception (FR-006) |
| `http_method`, `http_path`, `http_status`, `duration_ms` | string / string / int / float | only on the access-log line | Emitted once per completed request by the request-logging middleware; never includes request/response body (FR-007) |
| *(free-form structured fields)* | any JSON-serializable scalar | optional, call-site-provided | e.g. `chunk_index`, `model_name`, `token_count`; MUST NOT be a raw ORM/DTO/row object (see research.md redaction decision) |
| *(raw content fields: `prompt`, `completion`, `query`)* | string | optional, gated | Present only when `log_debug_include_raw_content=True` **and** severity is `debug` (FR-011) |

### Validation rules

- `correlation_id`, when present, MUST be identical across every Log Entry
  produced while handling one inbound request or background job (FR-004;
  validated by SC-001).
- No Log Entry may contain a field whose name matches the redaction denylist
  (`api_key`, `token`, `password`, `authorization`, `*_secret`, `*_key`)
  with an unredacted value, regardless of `level` or debug flag (FR-005).
- Raw content fields (`prompt`, `completion`, `query`) MUST NOT appear on any
  Log Entry unless `log_debug_include_raw_content=True` (FR-011); this holds
  even when `level=debug` is otherwise reachable via `log_level` config.
- Every Log Entry MUST be valid JSON on its own (one object per line),
  independent of any other line (FR-001, SC-002).

### State / lifecycle

Not applicable — a Log Entry is not stored or mutated; it is emitted once
and is immutable thereafter. `correlation_id` is the only piece of state
that has a lifecycle, and that lifecycle belongs to the request/job (bound
at start, cleared at end), not to any individual Log Entry.

## Configuration additions (`app/core/config.py` `Settings`)

Not a data entity, but the input that governs Log Entry production;
recorded here since the spec's functional requirements (FR-002, FR-011)
depend on it:

| Setting | Type | Default | Fail-fast rule |
|---|---|---|---|
| `log_level` | string | `"INFO"` | MUST be one of the standard severity names (case-insensitive); invalid value raises at startup, per Principle VII (FR-002) |
| `log_debug_include_raw_content` | bool | `False` | No validation beyond type coercion; startup emits one `WARNING` log line if `True` (FR-011) |
