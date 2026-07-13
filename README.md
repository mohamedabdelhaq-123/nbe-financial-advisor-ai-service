# nbe-financial-advisor-ai-service

Internal FastAPI AI service for the NBE AI-PFM platform.

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
