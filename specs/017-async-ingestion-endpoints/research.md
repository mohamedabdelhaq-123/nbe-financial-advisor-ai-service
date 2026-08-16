# Research: Async Ingestion Endpoints

Phase 0 for [spec.md](spec.md). Inputs, not open questions: the spec's clarifications (single
instance, self-contained status reads, service-side success criteria) and the requester's
planning-time decisions — **SAQ as the job queue, on the Postgres backend, with the worker running
in-process in the API's lifespan**.

Everything below about SAQ is verified against the library's published source
(`tobymao/saq@master`), not recalled — the defaults in §2 in particular would silently break this
feature if taken on trust.

## 1. Execution: SAQ on Postgres, worker in-process

**Decision**: `saq[postgres]` provides the queue and the worker. A `PostgresQueue` points at the
service's **own** DB; a `Worker` with the two job functions is constructed and `await worker.start()`
is driven as a lifespan-owned task, alongside the existing checkpointer setup. No Redis, no second
container, no separate worker process.

**Rationale**: The requester asked for an idiomatic library rather than hand-rolled persistence.
Among the candidates, SAQ on Postgres is the only one that adds no infrastructure: it reuses the
Postgres this service already owns and the `psycopg`/`psycopg_pool` driver already in
`pyproject.toml` (pulled in today by `langgraph-checkpoint-postgres`). arq was the initial choice but
is in **maintenance-only mode since 18 Oct 2025** (`python-arq/arq#510`: *"we won't archive this repo
so you can comment and submit fixes, but don't expect work on new fixes"*), which sits badly against
Principle VIII's "well-maintained library" wording for new infrastructure in a financial service. SAQ
is explicitly modelled on arq, is actively released (0.26.4, May 2026), and supports both backends.

**Verified against source**:
- `saq/queue/postgres.py` imports `AsyncConnection` from `psycopg` and `AsyncConnectionPool` from
  `psycopg_pool` — the driver is psycopg v3, already a dependency here (runtime SQLAlchemy stays on
  asyncpg; the two coexist, exactly as they already do for the checkpointer).
- `Worker.start()` is `async def start(self) -> None: """Start processing jobs and upkeep tasks."""`
  — awaitable inside an existing event loop, with a matching `async def stop()`. The CLI runner is a
  separate module-level function that creates its own loop; we do not need it.
- `PostgresQueue.connect()` calls `init_db()`, which applies SAQ's own migration list and records
  progress in a `saq_versions` table, creating `saq_jobs` and `saq_stats`.

**Precedent for the in-process, library-managed-schema shape**: this is already how
[app/features/chat/checkpointer.py](../../app/features/chat/checkpointer.py) works — `build_checkpointer()`
opens an `AsyncConnectionPool` from the same own-DB settings and `setup_checkpointer()` calls
`saver.setup()`, which creates `checkpoints`, `checkpoint_blobs`, and `checkpoint_writes` at startup,
outside Alembic. SAQ's `init_db()` is the same pattern with the same trade-off, so this feature is
matching an accepted convention rather than introducing one.

**Risk to settle at implementation time**: `Worker.start()` registers signal handlers. Inside a
uvicorn process, uvicorn also installs SIGTERM/SIGINT handlers, and whichever registers last wins.
This needs to be checked on the real process before it is trusted — if SAQ's handlers displace
uvicorn's, graceful shutdown breaks. Fallbacks, in order of preference: pass the worker its own
handling options if the version supports opting out, or drive the worker's processing loop directly
instead of `start()`, or fall back to a separate worker container (the topology explicitly not chosen
here). This is a genuine unknown, flagged rather than assumed away.

**Alternatives considered**:
- *arq* — the requester's first choice; rejected on maintenance status (above) after that was
  surfaced. SAQ keeps the same programming model.
- *procrastinate* — Postgres-native and actively maintained, but a different API and its own
  migration tooling with no arq lineage; SAQ covers the same ground with the requested shape.
- *Celery on the backend repo's Redis* — rejected: a separate worker process reopens the
  multi-process claiming problem FR-019 defers, and sharing a broker couples two services' failure
  domains.
- *`BackgroundTasks` + an owned job table* — the previous iteration of this plan; superseded.

## 2. SAQ defaults that MUST be overridden

Three of SAQ's defaults are actively wrong for this feature. Recording them here because each fails
in a way that looks like a bug in our code rather than a configuration mistake.

| Setting | SAQ default | Required here | Why |
|---|---|---|---|
| `timeout` | **10 seconds** | `0` (disabled) or a generous ceiling | Verified in `saq/job.py`: *"maximum amount of time a job can run for in seconds, defaults to 10 (0 means disabled)"*. A multi-page extraction runs for minutes; left at the default, **every real job would be killed at 10 seconds**. |
| `ttl` | **600 seconds** | `2592000` (30 days) | *"maximum time in seconds to store information about a job including results, defaults to 600"*. FR-016 wants 30 days; the default would delete results ten minutes after completion. |
| `retries` | 1 | 1 (unchanged, deliberately) | The spec defines no retry semantics — a failed step is re-driven by the caller's explicit retry (spec Assumptions). Silent re-execution would also double the audit rows FR-015 relies on. |

`heartbeat` (default 0, disabled) must be set for the stuck-job detection §5 depends on, and
`Worker(concurrency=...)` defaults to 10 — see §3.

## 3. Concurrency: SAQ's `concurrency`, not a hand-rolled bound

**Decision**: The bound is `Worker(concurrency=...)`, set explicitly to a documented constant. This
supersedes both earlier positions — the spec's original "fixed constant of 2" and the requester's
subsequent "no ceiling".

**Rationale**: The earlier objection was to *hand-rolling* a semaphore, not to bounding as such; a
worker's concurrency setting is the library's own knob and costs nothing to honor. Unbounded is not
really available anyway — `concurrency` is a worker property with a default of 10, so the only real
question is what number to put there. FR-012 should be restated a final time in these terms.

## 4. What SAQ owns, what we still own — and the dedup/retry conflict

**Decision**: SAQ's `saq_jobs` is the job record. We keep **one slim owned table** that maps a target
to its most recent job key, and nothing else: `(step, target_id, job_key, submitted_at)`, unique on
`(step, target_id)`. It holds no state, no result, and no financial content.

**Rationale — this is the one place the library does not fit the spec cleanly.** SAQ's `key` is
documented as *"unique identifier of a job, defaults to uuid1, can be passed in to avoid duplicate
jobs"*, which looks like FR-010 for free via a deterministic key such as `process:{statement_id}`. It
isn't, because of `ttl`: with results retained 30 days (§2), a *completed* job's record is still
present under that key, so a legitimate retry (FR-011) would collide with a finished job rather than
starting a new one — and resolving that collision by overwriting would violate FR-008's "terminal
states never change". Deterministic keys satisfy FR-010 at the cost of FR-011; random keys satisfy
FR-011 at the cost of FR-010. Neither is acceptable, so submission needs one lookup of its own:

1. Validate the target against the read-only backend DB (§9).
2. Read our row for `(step, target_id)`. If present, ask SAQ for that `job_key`'s status.
   - Non-terminal (`NEW`/`QUEUED`/`ACTIVE`) → return that key. No second execution (FR-010).
   - Terminal, or unknown to SAQ because it aged out → enqueue a new job, update the row's
     `job_key` (FR-011).
3. No row → enqueue and insert, via `ON CONFLICT DO NOTHING` so a concurrent duplicate submission
   resolves to one row.

**Alternatives considered**:
- *Query `saq_jobs` directly for an active job matching the target* — rejected: it means reading the
  library's internal table and its serialized kwargs, which is exactly the coupling we would be
  taking on the library to avoid.
- *Keep the full owned job table from the previous plan* — rejected: two durable records for one job
  is worse than either pure option, and it would put a second copy of the result back in our schema.

## 5. Result and failure content

**Decision**: The job function returns a JSON envelope that SAQ stores as the job result:
`{"ok": true, "result": {...}}` on success, `{"ok": false, "error": "<detail>"}` for an expected
pipeline failure. Unexpected exceptions are allowed to propagate.

**Rationale**: SAQ's `error` field is documented as *"stack trace if a runtime error occurs"* — not
something to hand a caller. FR-007 wants the same human-readable diagnostic the blocking endpoint
produces (`"document processing engine failed: …"`), which lives in the `HTTPException.detail` those
service functions raise. Catching `HTTPException` in the job function and returning it in the
envelope preserves that fidelity exactly; letting genuinely unexpected exceptions propagate leaves
SAQ to record `FAILED` with its stack trace, which the status route maps to a generic message while
logging the trace. So a caller never receives a stack trace, and an operator never loses one.

Consequently the status route derives our four states from SAQ's `Status` enum (verified values:
`NEW`, `QUEUED`, `ACTIVE`, `ABORTING`, `ABORTED`, `FAILED`, `COMPLETE`) *and* the envelope:

| SAQ status | Our state |
|---|---|
| `NEW`, `QUEUED` | `queued` |
| `ACTIVE` | `running` |
| `COMPLETE` + `ok: true` | `succeeded` |
| `COMPLETE` + `ok: false` | `failed` (envelope's `error`) |
| `FAILED`, `ABORTED`, `ABORTING` | `failed` (generic message; trace stays in logs) |

The financial result content therefore lives in `saq_jobs.result` — one durable copy in the own DB,
not two. That is a net improvement on the previous design's Principle III position, and FR-006a's
protections attach to that column: reachable only through the authenticated status route, never
logged, deleted when SAQ's sweep passes its `expire_at`.

## 6. Restart behavior — and the FR-009 amendment it forced

**Decision**: Drop the bespoke startup sweep. Rely on SAQ: queued jobs survive a restart in
`saq_jobs` and are dequeued again when the worker comes back; jobs orphaned mid-execution are caught
by SAQ's sweep, which (per `saq/queue/postgres.py`) handles stuck active jobs and deletes terminal
rows past `expire_at`.

**This diverged from the spec, and the spec was changed rather than the design.** FR-009 originally
said *any* job left non-terminal by a restart must be resolved to `failed`. SAQ instead **resumes**
queued work, which is strictly better for the caller — no spurious failure, no resubmission needed.
FR-009 now distinguishes the two cases (queued resumes; executing is swept to `failed` and not
re-executed, `retries=1`), SC-005 is bounded by the sweep interval rather than a fixed minute, and
the restart edge case and "best-effort execution" assumption were brought into line.

**To verify at implementation**: SC-005's one-minute bound now depends on SAQ's sweep timer and on
jobs carrying a `heartbeat` (default 0 = disabled, §2). Both need setting deliberately and the timing
confirmed against a real restart, since neither default gives the bound for free.

## 7. Database sessions inside a job

**Decision**: The job function opens its own sessions and passes the existing `get_backend_session` /
`get_own_session` generator functions straight through to `process_statement()` /
`normalize_statement()`, unchanged.

**Rationale**: Those functions consume their argument as `async for session in session_gen()`, which
works identically inside a worker task and inside a request — no FastAPI machinery involved, so no
adapter is needed. (Contrast the analytics slice, which had to wrap the same dependency in
`asynccontextmanager` because *its* jobs use `async with`.) Note the worker's psycopg pool is
SAQ's own and is unrelated to the app's SQLAlchemy engine; job code must not reach for it.

## 8. Reusing the blocking services, and the audit trail

**Decision**: The job functions call the existing `process_statement()` / `normalize_statement()`
unmodified.

**Rationale**: This is what makes FR-006 (identical result), FR-007 (identical diagnostics), SC-004
(equivalence across the existing suite), and FR-015 (same audit row, same action) true by
construction rather than by parallel implementation — the audit write lives inside those functions.
It also keeps FR-014 trivially satisfied: the blocking endpoints keep calling the same functions and
are untouched.

## 9. HTTP surface

**Decision**: Three routes on the existing ingestion router, inheriting its `Depends(require_token)`
(FR-013):

| Route | Success | Body |
|---|---|---|
| `POST /internal/ingestion/jobs/process` | `202` | reuses `ProcessStatementRequest` |
| `POST /internal/ingestion/jobs/normalize` | `202` | reuses `NormalizeStatementRequest` |
| `GET /internal/ingestion/jobs/{job_id}` | `200` | — |

The job reference is SAQ's `job.key` — a string, SAQ-generated (uuid1 by default), returned as-is
rather than wrapped in an identifier of ours. Typed as `str` in the response schema, not `UUID`,
since the key's format is SAQ's business. Full shapes in
[contracts/ingestion-jobs.md](contracts/ingestion-jobs.md).

## 10. Submission-time target validation

**Decision**: Submission resolves the target against the read-only backend DB — `StatementFile` by
`statement_id`, `StatementOcrResult` by `ocr_result_id` — and returns `404` with nothing enqueued
when it is absent (FR-003). A target deleted *after* submission is caught by the pipeline's existing
404 and surfaces as a failed job.

**Rationale**: Both lookups already exist inside the service functions; submission needs the
existence check without the work, so the jobs module issues the same narrow `SELECT` rather than
refactoring functions FR-014 wants left alone. Projecting existence only also matches Principle III's
egress-layer minimization rule.

## 11. Testing

**Decision**: Unit tests mock the queue at the submission boundary (assert "enqueued with these
arguments", assert the status mapping table in §5 for every SAQ status). Anything involving real SAQ
storage — enqueue/dequeue, the dedup lookup, sweep behavior, retention — runs against the existing
Testcontainers Postgres.

**Notes that will otherwise cost time**:
- SAQ creates its own tables on `connect()`, so integration tests need no fixture work for
  `saq_jobs`; but `tests/conftest.py`'s `create_all` path builds *our* tables only from imported
  model modules, so the slim mapping table's module must be imported there (the file already
  documents this exact trap for `AiAuditLog`).
- The Postgres backend needs a real database, so there is no offline unit path through real SAQ —
  which is why the status-mapping logic should be a pure function over `(saq_status, envelope)`,
  testable without a queue at all.
- No test needs Redis. Constitution I's offline requirement is unaffected.

## 12. Deployment and documentation

**Decision**: `pyproject.toml` gains `saq[postgres]`; `psycopg` is already present. FR-019's
single-instance constraint is documented in the README's *Production deployment* section and on the
`ai-service` block in [compose/docker-compose.prod.yml](../../compose/docker-compose.prod.yml).

**Rationale**: Single-instance matters less than it did — SAQ's Postgres backend claims jobs
atomically, so a second replica would no longer double-execute work, which was the sharpest edge of
FR-019. It still holds for now because it is a spec constraint and because nothing about multi-replica
operation has been tested here; but it is worth recording that adopting SAQ removes the *technical*
obstacle the constraint existed to work around. A future horizontal-scale feature would mostly need
to re-examine the worker topology, not build claiming from scratch.
