# Data Model: Async Ingestion Endpoints

Phase 1 for [spec.md](spec.md); decisions and rationale in [research.md](research.md). The job record
itself belongs to SAQ; this service adds one slim mapping table and no backend-DB write path.

## Storage owned by SAQ

`PostgresQueue.connect()` runs SAQ's own migrations against the **own** DB and creates:

| Table | Purpose |
|---|---|
| `saq_jobs` | The job record — key, function, kwargs, status, `queued`/`started`/`completed`/`touched` timestamps, `result`, `error`, `attempts`, `expire_at` |
| `saq_stats` | Worker statistics |
| `saq_versions` | SAQ's own schema-version bookkeeping |

These are **not** in `OwnBase.metadata` and are not managed by Alembic — SAQ creates and migrates
them itself at startup, the same arrangement the LangGraph checkpointer already has for
`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` (research.md §1).

Configuration that this feature depends on, none of it SAQ's default (research.md §2):

| Setting | Value | Consequence if left at default |
|---|---|---|
| `timeout` | `0` (disabled) | Every real extraction killed at 10s |
| `ttl` | `2592000` (30 days) | Results deleted 10 minutes after completion, breaking FR-016 |
| `retries` | `1` | Silent re-execution, doubling audit rows |
| `heartbeat` | set deliberately | Orphaned jobs never swept (research.md §6) |
| `concurrency` | documented constant | — |

### `saq_jobs.result` and Principle III

The normalization result — full transaction detail and the unmasked account number — lives in
`saq_jobs.result` as JSON. This is **one** durable copy in the own DB, not two: FR-006's
self-contained status read is satisfied by SAQ's own record rather than by a duplicate of ours.
FR-006a's protections attach to that column: reachable only through the authenticated status route,
never written to logs or telemetry, and deleted by SAQ's sweep once `expire_at` passes
(`DELETE ... WHERE status IN ('aborted','complete','failed') AND now >= expire_at`).

## Entity: Job Target Mapping (owned)

The one table this service owns. Own-DB, on `OwnBase`, in
`app/features/ingestion/jobs/models.py`. Exists solely to make FR-010 and FR-011 both true
(research.md §4) — it carries no state, no result, and no financial content.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `Integer` | no | PK, autoincrement — matches `AiAuditLog`'s convention for a bookkeeping table. |
| `step` | `String(20)` | no | `process` \| `normalize`. |
| `target_id` | `Uuid` | no | `statement_files.id` or `statement_ocr_results.id`. **Logical reference only — no `ForeignKey`** (Principle IV). |
| `job_key` | `String(64)` | no | The most recent SAQ job key for this target. Replaced on every accepted retry. |
| `submitted_at` | `DateTime(timezone=True)` | no | When that most recent job was enqueued. Bookkeeping only — the caller-facing timestamps come from `saq_jobs`. |

**Unique constraint**: `(step, target_id)` — exactly one row per target per step, for the lifetime of
that target. No partial predicate is needed, because the row tracks *the latest* job rather than *an
active* one; liveness is a question for SAQ.

**Validation**: `target_id` is never validated by the database. Submission validates it against the
read-only backend DB (FR-003); afterwards the reference may dangle and execution surfaces that as a
failed job.

**Growth**: one row per (statement, step) forever — bounded by statement count, holding no sensitive
data. Rows outlive the `saq_jobs` records they point at; a `job_key` unknown to SAQ is treated as
terminal by the submission path (research.md §4), which is exactly the behavior a retry needs.

## Submission flow

```
validate target ──404──► no enqueue, no row
      │
      ▼
  read mapping row for (step, target_id)
      │
      ├── none ─────────────► enqueue → INSERT ... ON CONFLICT DO NOTHING → return new key
      │
      └── found ──► ask SAQ for job_key's status
                        ├── NEW/QUEUED/ACTIVE ──► return the existing key   (FR-010)
                        └── terminal / unknown ─► enqueue → UPDATE job_key  (FR-011)
```

## State derivation

Our four contract states are derived, not stored — from SAQ's `Status` plus the result envelope the
job function returns (research.md §5):

| SAQ status | Envelope | Our `state` | `result` | `error` |
|---|---|---|---|---|
| `NEW`, `QUEUED` | — | `queued` | null | null |
| `ACTIVE` | — | `running` | null | null |
| `COMPLETE` | `ok: true` | `succeeded` | envelope's `result` | null |
| `COMPLETE` | `ok: false` | `failed` | null | envelope's `error` |
| `FAILED`, `ABORTED`, `ABORTING` | — | `failed` | null | generic message; stack trace stays in logs |
| job key unknown to SAQ | — | — | — | `404` (aged out or never existed) |

Terminal states never change afterwards (FR-008), because the only further operation on a terminal
`saq_jobs` row is deletion by the sweep.

## Module layout (ingestion slice)

```text
app/features/ingestion/jobs/
├── __init__.py     # slice-internal exports
├── queue.py        # PostgresQueue construction from own-DB settings, Worker wiring, the
│                   #   timeout/ttl/retries/heartbeat/concurrency constants
├── models.py       # IngestionJobTarget (the mapping table above)
├── schemas.py      # JobSubmissionResponse, JobStatusResponse (request bodies reused from
│                   #   app/features/ingestion/schemas.py — unchanged)
├── service.py      # target validation, the submission flow above, status read + state derivation
└── tasks.py        # the two SAQ job functions; call the existing pipeline services, catch
                    #   HTTPException, return the result envelope
```

## Response schemas

Request bodies are the existing `ProcessStatementRequest` / `NormalizeStatementRequest`, reused
verbatim — the async submission takes the same input as its blocking counterpart, which is what lets
the caller migrate one step at a time (FR-014).

**`JobSubmissionResponse`**:

| Field | Type | Notes |
|---|---|---|
| `job_id` | `str` | SAQ's job key. A string, not a `UUID` — the format is SAQ's business (research.md §9). |
| `step` | `str` | `process` \| `normalize`. |
| `state` | `str` | `queued`, or `running` when a repeat submission resolves to a job already executing (FR-010). |
| `submitted_at` | `datetime` | From `saq_jobs.queued`; on a deduplicated repeat, the *original* submission time. |

**`JobStatusResponse`** — a superset:

| Field | Type | Notes |
|---|---|---|
| `job_id`, `step`, `state`, `submitted_at` | | as above |
| `target_id` | `UUID` | Echoes what the job acts on. |
| `started_at` | `datetime \| None` | From `saq_jobs.started`; null while queued. |
| `finished_at` | `datetime \| None` | From `saq_jobs.completed`; null until terminal. |
| `result` | `dict \| None` | Only on `succeeded`. Byte-for-byte the blocking endpoint's response body for that step (FR-006). Open `dict` because the two steps differ and `normalized_json` is already open. |
| `error` | `str \| None` | Only on `failed` (FR-007). |

SAQ's timestamps are epoch seconds; the schema converts to timezone-aware UTC datetimes at this
boundary so the contract matches the rest of the API.

## Audit records

No new audit entity. The `ingestion.process` / `ingestion.normalize` rows are written by the existing
service functions the job functions call, so an async execution produces exactly the audit record its
blocking counterpart produces (FR-015). Submission writes no audit row — no privileged work has
happened yet.
