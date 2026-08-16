# Implementation Plan: Async Ingestion Endpoints

**Branch**: `017-async-ingestion-endpoints` | **Date**: 2026-07-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/017-async-ingestion-endpoints/spec.md`

## Summary

Add a submit-and-poll surface alongside today's blocking ingestion endpoints: `POST
/internal/ingestion/jobs/process` and `.../jobs/normalize` accept work and acknowledge immediately
with a job reference; `GET /internal/ingestion/jobs/{job_id}` reports
`queued`/`running`/`succeeded`/`failed` and carries the full result or the failure reason.

Execution and persistence come from **SAQ** on its **Postgres** backend, with the worker running
**in-process** in the API's lifespan. SAQ owns the job record, the queue, timestamps, retention, and
sweep; this service adds a slim mapping table so a target's in-flight job can be found (FR-010)
without blocking a retry once it is terminal (FR-011). The job functions call the *existing*
`process_statement()` / `normalize_statement()` unchanged, which is what makes result equivalence,
error fidelity, and the audit trail identical to the blocking path by construction rather than by
parallel implementation.

No Redis, no second container, no new database — SAQ's Postgres backend uses the own DB and the
`psycopg` driver already present for the LangGraph checkpointer, which is also the precedent for a
library managing its own tables outside Alembic.

**Decision history worth carrying**: the requester chose `BackgroundTasks` over a lifespan-owned
`asyncio` task, then dropped the spec's concurrency bound, then asked for a real queue library and
chose arq. arq turned out to be in maintenance-only mode since Oct 2025, so SAQ — arq-inspired,
actively maintained, and able to run on Postgres — was selected instead, with the worker in-process
so FR-019's single-instance framing survives. The concurrency bound returns as SAQ's `concurrency`
setting, which is a library knob rather than the hand-rolled semaphore that was objected to.

## Technical Context

**Language/Version**: Python 3.12 (existing service; venv is 3.12.12)

**Primary Dependencies**: One new dependency, `saq[postgres]` (0.26.4, actively maintained). Its
driver, `psycopg`/`psycopg_pool`, is already in `pyproject.toml` via `langgraph-checkpoint-postgres`.
SQLAlchemy 2.0 async on asyncpg continues to serve everything else; the two drivers coexist exactly
as they already do for the checkpointer. arq was rejected on maintenance status and Celery/procrastinate
on fit — see research.md §1.

**Storage**: SAQ creates and migrates `saq_jobs` / `saq_stats` / `saq_versions` in the **own** DB at
startup, outside Alembic. This service adds one small Alembic-managed table
(`ai_ingestion_job_targets`) holding `(step, target_id, job_key, submitted_at)` and nothing else. The
pipeline result — including the unmasked account number — lives in `saq_jobs.result` with a 30-day
`ttl`; no second copy is stored. No backend-DB schema change and no backend-DB write path.

**Testing**: `pytest`, mock-first (Constitution I). The status-derivation logic is a pure function
over `(saq_status, envelope)` so every mapping row is unit-testable with no queue at all; submission
tests mock the queue at the enqueue boundary. Real-SAQ behavior (enqueue/dequeue, the dedup lookup,
sweep, retention) runs against the existing Testcontainers Postgres. No test needs Redis or a real
model.

**Target Platform**: Linux container via `compose/docker-compose.prod.yml`, single instance
(FR-019). `Dockerfile` runs `uvicorn app.main:app` with no `--workers`, so one container is one event
loop — and now also one worker.

**Project Type**: Existing single-project FastAPI service. Adds one subpackage
(`app/features/ingestion/jobs/`) inside the existing ingestion slice; no new slice, service, or
container.

**Performance Goals**: SC-001 — submission acknowledges in under 2s for 95% of submissions
(validation `SELECT` + dedup lookup + enqueue, all DB-bound, none of it pipeline work). SC-003 — no
async interaction holds a connection past 60s. SC-005 — needs re-derivation, since it now depends on
SAQ's sweep interval and job `heartbeat` rather than a startup sweep of ours (research.md §6).

**Constraints**: Three SAQ defaults are actively wrong here and must be overridden — `timeout` (10s,
would kill every real extraction), `ttl` (600s, would delete results ten minutes after completion),
and `heartbeat` (0, disables the stuck-job sweep SC-005 depends on). Concurrency is SAQ's
`concurrency` setting, a documented constant. FR-019's single-instance requirement still holds as a
spec constraint, though SAQ's atomic claiming removes the technical hazard it was written for. FR-014
requires the blocking endpoints and their service functions to stay behaviorally unchanged. Every
success criterion is provable in this repository; the backend-side migration onto this surface is out
of scope.

**Scale/Scope**: New `app/features/ingestion/jobs/` subpackage (6 modules), additions to
`app/features/ingestion/router.py`, queue/worker wiring in `app/main.py`'s lifespan, one small
migration, `pyproject.toml`, deployment docs, and tests. No other feature slice is touched.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design below.*

| Principle | Assessment |
|---|---|
| I. Mandatory Automated Testing | **PASS.** The mapping table's dedup/retry logic and the SAQ→contract status derivation are both testable without live services — the latter as a pure function over `(status, envelope)`. Real-SAQ behavior runs on the existing Testcontainers Postgres, which is the mandated integration substrate anyway. No Redis, no real model. Two traps are recorded rather than left to be found: `tests/conftest.py`'s `create_all` only sees imported model modules, and there is no offline path through real SAQ, which is why the mapping logic must not be entangled with the queue. |
| II. Security & Secrets Discipline | **PASS.** All three routes hang off the ingestion router's existing `Depends(require_token)`. No new secrets or external endpoints — SAQ connects to the own DB with the credentials already configured. `saq[postgres]` is one new dependency and is subject to the CI dependency-vulnerability gate like any other. |
| III. Data Protection & Compliance (NON-NEGOTIABLE) | **CONDITIONAL PASS — improved over the previous design.** FR-006's self-contained status read still means the complete normalization result (full transaction detail, unmasked account number) is durable in the own DB, now in `saq_jobs.result` rather than in a table of ours. That is **one** copy instead of two, which is the material improvement. The justification is otherwise unchanged: (a) *purpose* — the async contract cannot deliver a result any other way; (b) *boundary* — this content already crosses this exact boundary today, since the blocking endpoint returns it to the same authenticated caller and `normalize_statement()` already writes `normalized.json` to object storage, so no new trust boundary and no new recipient; (c) *egress* — readable only through the authenticated status route, with FR-006a's "never in logs or telemetry" enforced by logging job keys and states only, and the job machinery makes no model call, so nothing new reaches the Langfuse export path; (d) *retention* — enforced by SAQ's sweep against `expire_at`, **which is only correct if `ttl` is set to 30 days**, since the default of 600s would delete results ten minutes after completion. That single setting now carries the whole retention requirement, so it belongs in a test, not just in configuration. The residual is recorded in Complexity Tracking and must be called out in the PR. |
| IV. Data Ownership & Access Boundaries | **CONDITIONAL PASS — a library now migrates tables in the own DB.** SAQ's `init_db()` creates and migrates `saq_jobs`/`saq_stats`/`saq_versions` at startup, outside Alembic. Read strictly, "own-DB metadata MUST be the *sole* Alembic `target_metadata`" still holds — SAQ's tables are not in `OwnBase.metadata`, so Alembic's scope is unchanged and no autogenerate will try to drop them. The principle's actual concern is the backend boundary, and that is untouched: our owned table's `target_id` is an unconstrained `Uuid` with **no** `ForeignKey`, and the only backend-DB interaction anywhere in this design is an existence `SELECT`. Precedent is decisive rather than merely convenient: `app/features/chat/checkpointer.py` already has LangGraph create `checkpoints`/`checkpoint_blobs`/`checkpoint_writes` in the own DB via `saver.setup()` in the lifespan. This feature matches an accepted convention; it does not invent one. |
| V. Feature-Bounded Modular Architecture | **PASS.** Everything lands in `app/features/ingestion/jobs/` — queue wiring, mapping model, schemas, service, job functions — inside the slice that owns ingestion. The job functions reach only into their own slice's service functions. |
| VI. LLM & Agent Architecture | **PASS / not applicable.** No agent, prompt, or model-access change. Normalization still runs through the same configurable model-access layer. |
| VII. Operational Readiness & Fail-Fast Configuration | **PASS, with two operational items.** No new user-facing settings; the SAQ constants live in code. `/health` and `/ready` stay auth-free and dependency-free. Queue connection and worker startup join the lifespan next to the checkpointer and should fail the same way — loudly, before ready. The two items: (1) `Worker.start()` registers signal handlers, and uvicorn does too, so shutdown behavior must be verified on the real process rather than assumed (research.md §1 lists fallbacks); (2) SC-005's timing now depends on SAQ's sweep interval and job `heartbeat`, so the one-minute bound must be measured, not inherited. |
| VIII. Library-First, Minimal Implementation | **PASS — this is the principle's central case.** Adopting a maintained queue library removes the hand-rolled job table, state machine, restart sweep, and retention loop the earlier design carried. The one piece deliberately kept is the slim mapping table, and only because SAQ's key-based dedup cannot satisfy FR-010 and FR-011 simultaneously under a 30-day `ttl` (research.md §4) — a genuine gap, not a preference. Library choice was made on evidence: arq is in maintenance-only mode since Oct 2025 (`python-arq/arq#510`), which is exactly what "well-maintained" is meant to exclude for new infrastructure in a financial service; SAQ keeps arq's programming model, is actively released, and needs no Redis. Every library claim here was verified against published source (`saq/job.py` defaults, `saq/queue/postgres.py` driver/schema/sweep, `Worker.start()`'s signature), not recalled. |

## Project Structure

### Documentation (this feature)

```text
specs/017-async-ingestion-endpoints/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── ingestion-jobs.md
└── tasks.md             # Phase 2 output (/speckit.tasks command — not created by this command)
```

### Source Code (repository root)

```text
app/features/ingestion/
├── router.py                       # edited: three new routes on the existing router, inheriting
│                                   #   require_token (FR-013). Blocking routes untouched (FR-014)
├── schemas.py                      # unchanged — submission bodies reused verbatim
├── service/                        # unchanged — process.py and normalize.py called as-is by the
│                                   #   job functions (FR-006/FR-007/FR-015 hold by construction)
└── jobs/                           # new subpackage
    ├── __init__.py
    ├── queue.py                    # new: PostgresQueue from own-DB settings; Worker wiring;
    │                               #   the timeout=0 / ttl=30d / retries=1 / heartbeat /
    │                               #   concurrency constants (research.md §2, §3)
    ├── models.py                   # new: IngestionJobTarget — (step, target_id, job_key,
    │                               #   submitted_at), unique on (step, target_id) (FR-010/FR-011)
    ├── schemas.py                  # new: JobSubmissionResponse, JobStatusResponse
    ├── service.py                  # new: target validation (FR-003), submission flow, status read
    │                               #   + the SAQ-status → contract-state derivation (FR-004/FR-008)
    └── tasks.py                    # new: the two SAQ job functions — call the existing pipeline
                                    #   services, catch HTTPException, return the result envelope

app/main.py                         # edited: lifespan connects the queue and starts the in-process
                                    #   worker alongside the checkpointer; stops both on shutdown

migrations/versions/<rev>_add_ingestion_job_targets.py   # new: the mapping table + unique constraint

pyproject.toml                      # edited: add saq[postgres] (psycopg already present)

tests/conftest.py                   # edited: import the new model module so the mapping table
                                    #   registers on OwnBase.metadata before create_all
tests/features/ingestion/
└── test_jobs.py                    # new: status derivation (every row of the mapping table),
                                    #   submission flow with the queue mocked, 404 on unknown target
tests/integration/
├── test_ingestion_jobs.py          # new: real SAQ on Testcontainers Postgres — enqueue/dequeue,
│                                   #   dedup of an in-flight target, retry after terminal,
│                                   #   ttl/sweep retention, repeatable terminal reads
└── test_migrations.py              # edited: assert the mapping table exists after upgrade head

README.md                           # edited: single-instance constraint (FR-019); note that the
                                    #   worker runs in-process
compose/docker-compose.prod.yml     # edited: single-instance comment on the ai-service block
```

**Structure Decision**: Existing single-project FastAPI service; no new project, slice, or container.
The async surface is a subpackage of the ingestion slice rather than a new "jobs" slice, because the
jobs *are* ingestion work — a separate slice would immediately have to reach into ingestion's service
functions, which Principle V forbids. Within the subpackage the split follows what each module talks
to: `queue.py` to SAQ, `service.py` to the request, `tasks.py` to the pipeline.

## Post-Design Constitution Check

*Re-checked after Phase 1 (data-model.md, contracts/, quickstart.md).*

The design artifacts surfaced three things the initial gate did not, none of which change a verdict:

- **Principle III now rests on one setting.** `ttl=2592000` is the entire retention mechanism —
  there is no purge loop of ours to fall back on. data-model.md states it as a required override with
  its failure mode; quickstart.md verifies it by back-dating `expire_at` rather than by reading
  configuration. It needs an assertion in the integration suite, not just documentation.
- **FR-009 and SC-005 were amended, not worked around.** SAQ *resumes* queued work after a restart
  instead of failing it — better for the caller, but contrary to the original wording. Rather than
  implement against a spec that says otherwise, FR-009 now distinguishes not-yet-started (resumes)
  from mid-execution (swept to `failed`, not re-executed), SC-005 is bounded by the sweep interval,
  and the restart edge case plus the "best-effort execution" assumption were brought into line.
- **Principle VIII's exception is narrow and stated.** The mapping table is the only hand-rolled
  persistence left, and data-model.md's submission flow shows exactly why SAQ's `key` dedup cannot
  cover both FR-010 and FR-011 under a 30-day `ttl`.

Principle IV is confirmed at the schema level (`target_id` unconstrained, backend DB read-only), and
the contract confirms Principle VIII by what it omits — no cancellation route, no listing route, no
progress percentage.

Gate remains **CONDITIONAL PASS** on the Principle III and Principle IV items below.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Durable copy of full transaction detail + unmasked account number in `saq_jobs.result` for 30 days (Principle III minimization) | FR-006 requires a status read to be self-contained — a succeeded job must carry its complete result without depending on another store. Settled at the spec level in the 2026-07-28 clarification, which required this justification rather than an internal-DB exemption | Storing an object-storage pointer and re-fetching on read was rejected in the spec itself: a status read that fails because object storage is briefly unreachable defeats the purpose of the async surface. Note this design *halves* the exposure the previous plan had — SAQ's record replaces our own duplicate rather than adding to it |
| A library creates and migrates tables in the own DB outside Alembic (Principle IV) | SAQ's Postgres backend calls `init_db()` on connect; there is no mode where it uses tables we migrate ourselves | Pre-provisioning SAQ's schema with our own Alembic migration was considered and rejected — it would pin us to SAQ's internal schema version and break on any upgrade that ships a new migration. The pattern is already accepted here: the LangGraph checkpointer does exactly this via `saver.setup()` |
| A slim owned mapping table alongside SAQ's job record | SAQ's `key`-based dedup satisfies FR-010 only with a deterministic key, which then collides with the 30-day-retained completed job on a legitimate retry (FR-011), and resolving the collision by overwrite would violate FR-008 | Querying `saq_jobs` directly for an active job matching the target was the alternative — rejected because reading the library's internal table and its serialized kwargs is precisely the coupling adopting a library is meant to avoid |
| Single-instance operational constraint (FR-019) | Retained as a spec constraint and because multi-replica operation is untested here | Notably, SAQ's atomic claiming *removes* the technical hazard FR-019 was written for — two instances would no longer double-execute a job. Lifting the constraint is now mostly a question of worker topology and testing, not of building claiming from scratch, and belongs to the future horizontal-scale feature |
