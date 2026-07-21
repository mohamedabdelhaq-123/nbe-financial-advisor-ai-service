# Quickstart: Validating Structured Logging Setup

Prerequisites: repo checked out at branch `012-structured-logging-setup`,
dependencies synced (`uv sync`), `.env` configured for mock mode
(`USE_MOCK_LLM=1`, `USE_MOCK_MINERU=1`) so no live provider is required.

## 1. Confirm every log line is structured JSON (FR-001, SC-002)

```bash
uv run uvicorn app.main:app --port 8000 2>&1 | tee /tmp/service.log
```

In another shell, hit any Django-facing endpoint (with the shared bearer
token) or the unauthenticated probes:

```bash
curl -s localhost:8000/health
```

Inspect `/tmp/service.log`: every line must be a single valid JSON object
(`jq -c . </tmp/service.log` should error on none of them) and must include
`timestamp`, `level`, `logger`, and `event` fields (data-model.md → Log
Entry). Confirm uvicorn's own access-log lines are absent — only the
service's own structured access-log entry appears per request (research.md →
Access logging decision).

## 2. Confirm per-request correlation (FR-004, SC-001)

Issue two concurrent requests (e.g. two `curl` calls to a chat or analytics
endpoint run in parallel) and grep the log:

```bash
grep '"correlation_id"' /tmp/service.log | jq -r .correlation_id | sort | uniq -c
```

Each request's lines should share one `correlation_id`, distinct from the
other request's. For a request that fans out internally (statement
normalization with multiple chunks, or a chat turn invoking sub-agents),
confirm every resulting line — including ones from `asyncio.gather`-spawned
work — carries the same `correlation_id` as the originating request line.

## 3. Confirm unhandled-exception logging (FR-006)

Trigger a code path that raises (e.g. an intentionally malformed request
body against an endpoint with strict validation, or a temporary raise
inserted for this check). Confirm:
- The HTTP response still returns (no process crash).
- Exactly one `level: "error"` (or higher) Log Entry appears with `exception
  .type`, `.message`, and `.stacktrace` populated (data-model.md).

## 4. Confirm redaction and debug-mode gating (FR-005, FR-011, SC-003)

With default settings (`log_debug_include_raw_content` unset/`False`),
exercise the chat and ingestion/normalization paths and confirm:

```bash
grep -E '"(prompt|completion|query)"' /tmp/service.log   # expect no matches
grep -E '"(api_key|token|password|authorization)"' /tmp/service.log  # expect no unredacted matches
```

Then restart with `LOG_DEBUG_INCLUDE_RAW_CONTENT=1` and `LOG_LEVEL=DEBUG`,
repeat the same requests, and confirm:
- A `level: "warning"` startup line announcing raw-content logging is
  enabled appears once.
- Raw `prompt`/`completion`/`query` fields may now appear on `debug`-level
  lines only.
- Secret-shaped fields (`api_key`, `token`, etc.) are still never present
  unredacted, even in this mode (FR-005 is unconditional).

## 5. Confirm log level is config-driven, no code change (SC-004)

```bash
LOG_LEVEL=WARNING uv run uvicorn app.main:app --port 8000
```

Confirm `info`-level lines (e.g. the per-request access log) no longer
appear, while `warning`/`error` lines still do — achieved purely via the
environment variable, no code edit.

## 6. Confirm a bad `LOG_LEVEL` fails fast (FR-002, Principle VII)

```bash
LOG_LEVEL=NOT_A_LEVEL uv run uvicorn app.main:app --port 8000
```

Expect the process to exit immediately with a clear startup error, matching
the existing fail-fast pattern in `app/core/config.py` for other invalid
settings — never a silent fallback to a default level.
