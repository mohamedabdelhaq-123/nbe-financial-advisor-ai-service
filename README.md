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
