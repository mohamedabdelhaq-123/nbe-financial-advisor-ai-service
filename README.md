# nbe-financial-advisor-ai-service

Internal FastAPI AI service for the NBE AI-PFM platform.

## Running locally

This service has no compose files of its own anymore — the sibling
`nbe-financial-advisor-backend` repo's `deploy/` directory holds the single
consolidated stack (Postgres, Redis, SeaweedFS, backend, celery-worker,
mock-bank-oauth/sync, this service, and the frontend), which also provisions
the `ai_appdb`/`ai_user`/`ai_readonly` roles this service needs (via
`deploy/initdb/10-ai-roles.sh`).

```bash
cp .env.example .env
# Edit .env so POSTGRES_PASSWORD / BACKEND_DB_PASSWORD / STORAGE_S3_ACCESS_KEY /
# STORAGE_S3_SECRET_KEY match the values actually set in the backend repo's own
# .env (AI_DB_PASSWORD, AI_READONLY_PASSWORD, SEAWEED_ACCESS_KEY, SEAWEED_SECRET_KEY).
# These aren't synced automatically across repos.

make dev-up   # alias for `docker compose -f ../nbe-financial-advisor-backend/deploy/docker-compose.dev.yml up --build`
```

`nbe-financial-advisor-backend/deploy/docker-compose.dev.yml` is the single
source of truth for the dev stack; `docker-compose.prod.yml` next to it is
the production equivalent. Both build this service directly (`target: dev` /
`target: prod`) as part of the one stack, rather than this repo running its
own separate compose project.

### LLM observability (Langfuse)

Every LLM call the service makes (chat, statement normalization, plan
generation, embeddings) is auto-instrumented and traced to Langfuse — no
per-call-site changes. `LANGFUSE_ENABLED=true` and a matching
`LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are already
`.env.example`'s defaults, intended to point at a local self-hosted Langfuse
v3 stack (its own Postgres, ClickHouse, Redis, and MinIO — see
`compose/langfuse/docker-compose.yml`, vendored from upstream). **Not
currently wired into `make dev-up`** — the consolidated dev stack in
`nbe-financial-advisor-backend/deploy/` doesn't start it (it would collide on
service names — that file already has its own `postgres`/`redis`), and
there's no separate invocation set up yet either. Until that's built, either
point at a cloud-hosted Langfuse instance (set the three `LANGFUSE_*` vars to
its real values) or set `LANGFUSE_ENABLED=false` to disable tracing outright
— the only state where the three connection settings aren't required
(leaving them unset while `LANGFUSE_ENABLED=true` fails startup immediately
rather than silently degrading).

See `specs/013-langfuse-observability/quickstart.md` for the original
validation walkthrough — written against the pre-consolidation compose setup,
so its exact commands are stale, but the Langfuse config/behavior it
describes still holds.

### Production deployment

`nbe-financial-advisor-backend/deploy/docker-compose.prod.yml` is the real
deployment path: one stack, fronted by nginx on the `nbe-prod` network, that
builds this service directly (`target: prod`) alongside everything else —
`backend`/`celery-worker` reach it at `http://ai-service:8001` inside that
same stack. All runtime config comes from `.env`, same as dev.

```bash
make prod-up    # build + start, detached
make prod-down  # stop
```

#### Run exactly one instance

**This service must run as a single instance, and uvicorn must run with a single
worker process.** Asynchronous ingestion jobs are submitted via
`/internal/ingestion/jobs/*` and read back via the generic `/internal/tasks/{job_id}`;
both execute inside the API process itself: the SAQ worker starts in the app lifespan,
so every replica or extra uvicorn worker is another worker competing for the same queue.

The queue claims jobs atomically, so a second instance would not double-execute a job —
but nothing else about multi-instance operation has been tested here, and the
concurrency ceiling is per-worker, so N replicas mean N times the configured concurrent
MinerU/LLM load. Adding replicas is a deliberate change, not a scaling knob: see
`specs/017-async-ingestion-endpoints/` before making one.

Jobs live in the service's own database (SAQ's `saq_jobs`, created automatically at
startup — not an Alembic migration) and are retained for 30 days after they finish. A
job interrupted by a restart is either resumed, if it had not started, or reported as
failed, if it was mid-execution; the caller resubmits.

## Backend mirror models

The service reads specific backend (Django-owned) tables through a **read-only**
connection and never writes them. Those tables are mirrored as **generated** typed
SQLAlchemy models in [`app/backend_db/models.py`](app/backend_db/models.py), bound to
`BackendBase` (which is excluded from Alembic). Per Constitution Principle IV the file is
**generated, never hand-edited** — there is no committed schema snapshot and no CI/scheduled
automation; you regenerate it directly from the live backend and commit the result.

### Regenerate

The generator reads the same `BACKEND_DB_*` settings the app uses, from the repo's
`.env` and/or the environment (real env vars override `.env`). Point them at a
**read-only** backend role. The host must be reachable from where you run the
command: inside the compose network `BACKEND_DB_HOST=postgres`, but from your host
use a reachable host/port (the postgres container IP, or a published port).

```bash
# .env (or exported):
#   BACKEND_DB_HOST=...   BACKEND_DB_NAME=...   BACKEND_DB_USER=ai_readonly
#   BACKEND_DB_PASSWORD=...   BACKEND_DB_PORT=5432   BACKEND_DB_SCHEMA=public  (optional)

make gen-backend-models TABLES="auth_user accounts_account"
# or directly:
uv run --group codegen python scripts/gen_backend_models.py --tables auth_user accounts_account

# omit the table list to mirror ALL backend tables:
make gen-backend-models

# one-off override without touching .env:
BACKEND_DB_HOST=127.0.0.1 BACKEND_DB_PORT=5433 make gen-backend-models TABLES="users"
```

Tables referenced by foreign keys are pulled in automatically. The generator rebinds the
models to `BackendBase` and formats the output (ruff + black) so it passes CI unchanged.
Review the diff and commit `app/backend_db/models.py`.

**Consuming the mirror:** query via `get_backend_session()` and project only the columns a
feature needs into a redacted DTO before the data crosses any trust boundary — the models
mirror full tables, so data minimization lives at the query/DTO layer (Constitution
Principle III), not the model.

## Phase 2 — `/internal/*` API surface

All endpoints below require a `Bearer <AI_SERVICE_TOKEN>` header unless noted.

### API Documentation

Interactive docs are served at `/docs` (Swagger UI) and `/redoc` (ReDoc), generated from the
same request/response models the API validates against. When adding or changing an
`/internal/*` endpoint, review it against
[`specs/006-api-documentation/contracts/openapi-enrichment-contract.md`](specs/006-api-documentation/contracts/openapi-enrichment-contract.md),
the completeness checklist for descriptions, examples, and error responses (enforced by PR
review, not CI).

### Chat — Conversational assistant

| Endpoint | Description |
|---|---|
| `POST /internal/chat` | SSE streaming chat (Maestro intent routing) |

### Analytics — Deterministic insight pipelines

| Endpoint | Description |
|---|---|
| `POST /internal/analyze/post-ingestion` | Run all three pipelines at once |
| `POST /internal/analyze/monthly-summary` | Monthly spend aggregation + embedding |
| `POST /internal/analyze/anomaly-check` | Per-category IQR outlier detection |

### Budget planning

| Endpoint | Description |
|---|---|
| `POST /internal/plan/question` | Get next questionnaire question |
| `POST /internal/plan/generate` | Generate 100%-sum budget allocation |

### Recommendations

| Endpoint | Description |
|---|---|
| `POST /internal/recommendations/match` | RAG product match via pgvector cosine |

### Health probes (no auth)

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness check |
| `GET /ready` | Readiness check |

### Data contract

**This service never writes to the backend (Django-owned) database.** All analytics
results, embeddings, and computed insights are **returned** to the caller (Django persists
them). The own-DB holds only AI-specific tables (audit logs, checkpointer state, problem
statements, recommendation logs) and is the only database this service migrates.
