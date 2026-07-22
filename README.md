# nbe-financial-advisor-ai-service

Internal FastAPI AI service for the NBE AI-PFM platform.

## Running locally

This repo's Postgres/S3 dependencies are **not** self-contained in dev — they're
provided by the sibling `nbe-financial-advisor-backend` repo's own dev stack, which
also provisions the `ai_appdb`/`ai_user`/`ai_readonly` roles this service needs
(via `deploy/initdb/10-ai-roles.sh`). Start that first:

```bash
cd ../nbe-financial-advisor-backend
docker compose up -d postgres seaweedfs   # publishes the shared "nbe-dev" network
```

Then in this repo:

```bash
cp .env.example .env
# Edit .env so POSTGRES_PASSWORD / BACKEND_DB_PASSWORD / STORAGE_S3_ACCESS_KEY /
# STORAGE_S3_SECRET_KEY match the values actually set in the backend repo's own
# .env (AI_DB_PASSWORD, AI_READONLY_PASSWORD, SEAWEED_ACCESS_KEY, SEAWEED_SECRET_KEY).
# These aren't synced automatically across repos.

make dev-up   # builds the `dev` image target, runs alembic, serves with --reload on :8001
```

`compose/docker-compose.yml` is the shared base service definition;
`compose/docker-compose.dev.yml` layers on hot reload, a published port, and
attaches to the backend's `nbe-dev` network.

### LLM observability (Langfuse)

Every LLM call the service makes (chat, statement normalization, plan
generation, embeddings) is auto-instrumented and traced to Langfuse — no
per-call-site changes. `LANGFUSE_ENABLED=true` and a matching
`LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are already
`.env.example`'s defaults, pointed at a local self-hosted Langfuse v3 stack
(its own Postgres, ClickHouse, Redis, and MinIO — see
`compose/langfuse/docker-compose.yml`) that starts with no signup step:
`langfuse-web` seeds its own admin account/project/API-key pair on first boot
via Langfuse's headless initialization, using those same `LANGFUSE_*` values.

That stack is opt-in — `make dev-up` alone does **not** start it, to keep the
base stack free of six extra containers for anyone not using local tracing:

```bash
make dev-up-observability   # dev-up + the local Langfuse stack
```

Without it, `ai-service` still starts fine (`LANGFUSE_ENABLED` defaults to
`true`) — it just fails open silently, since nothing is listening at
`LANGFUSE_HOST` yet; no effect on requests either way. To point at a
cloud-hosted Langfuse instead, set the three `LANGFUSE_*` vars to its real
values and skip `dev-up-observability`. To disable tracing outright, set
`LANGFUSE_ENABLED=false` (the only state where the three connection settings
aren't required — leaving them unset while `LANGFUSE_ENABLED=true` fails
startup immediately rather than silently degrading).

See `specs/013-langfuse-observability/quickstart.md` for the full validation
walkthrough.

### Production deployment

`compose/docker-compose.prod.yml` is the real deployment path for this
service: it builds the hardened `prod` image target and joins `nbe-prod`, the
external network created by
`nbe-financial-advisor-backend/deploy/docker-compose.yml` (that file no
longer builds/runs ai-service itself), so `backend`/`celery-worker` there can
reach it at `http://ai-service:8001`. All runtime config comes from `.env`,
same as dev — see that file's header comment for the network prerequisite.

```bash
make prod-up    # build + start, detached
make prod-down  # stop
```

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
