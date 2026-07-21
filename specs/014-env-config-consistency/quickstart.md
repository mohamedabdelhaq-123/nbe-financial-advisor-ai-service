# Quickstart: Validating Consistent, Fault-Tolerant Environment Configuration

Validates the feature end-to-end against the acceptance scenarios in [spec.md](spec.md) and the contract in [contracts/env-var-contract.md](contracts/env-var-contract.md). Assumes the implementation tasks (tasks.md, generated separately) are complete.

## Prerequisites

- Docker Compose, as already required to run this repo.
- A `.env` file copied from the updated `.env.example` (new `GROUP__FIELD` names).
- A checkout of `nbe-financial-advisor-backend` alongside this repo, for steps 5–6.

## 1. Every required group fails fast, individually (validates US1, FR-002, SC-002)

For each required field in contracts/env-var-contract.md §2 (`OWN_DB__POSTGRES_PASSWORD`, `BACKEND_DB__HOST`, `STORAGE__S3_BUCKET`, `AI_SERVICE_TOKEN`, etc.), in turn:

```sh
# example for one field — repeat per required field
OWN_DB__POSTGRES_PASSWORD= uv run python -c "from app.core.config import settings"
```

**Expected**: the process exits non-zero with a `ValidationError` (or equivalent startup failure) naming that exact field — not a generic "field required" with no field name, and not a delayed failure the first time a DB query actually runs.

## 2. A valid `.env` boots cleanly (validates US1-AS3, SC-001)

```sh
cp .env.example .env   # fill in real secrets where the template has placeholders
docker compose -f compose/docker-compose.yml up --build
```

**Expected**: `ai-service` starts with no configuration-related errors. This is the same command as today — no new flags, no `--env-file` needed for `ai-service`'s own values (contract §1).

## 3. `.env` is the single source of truth — no silent compose override (validates US2, FR-001, SC-003)

```sh
# set a non-default value in .env, e.g.:
#   CHAT_MODEL__MODEL_NAME=some-other-model
docker compose -f compose/docker-compose.yml up --build
curl -s -H "Authorization: Bearer $AI_SERVICE_TOKEN" http://localhost:8001/some-endpoint-that-echoes-config  # or check logs/startup output
```

**Expected**: the running service reflects the `.env` value. Inspect `compose/docker-compose.yml`'s `ai-service` service definition and confirm it has no `environment:` key at all — only `build:` and `env_file:` — so there is no second place a conflicting default could live.

## 4. Deterministic override still works (validates US2-AS3, FR-008)

```sh
make prod-smoke   # or: docker compose -f compose/docker-compose.yml -f compose/docker-compose.prod.yml up --build
```

**Expected**: boots successfully using `docker-compose.prod.yml`'s pinned dummy values (renamed per contract §1's naming convention) regardless of whatever is in the local `.env` — confirms the merge-precedence behavior from research.md §1 still holds with the base file's `environment:` block removed.

## 5. Credentials never render in plaintext (validates US3, FR-006, SC-004)

```sh
# trigger a validation failure and inspect the output
OWN_DB__POSTGRES_PASSWORD= uv run python -c "from app.core.config import settings" 2>&1 | grep -i "password\|secret\|key\|token"
# then, with valid config, inspect a normal debug print
uv run python -c "from app.core.config import settings; print(settings)" | grep -i "password\|secret\|key\|token"
```

**Expected**: any line matching those keywords shows the field name and a masked placeholder (`**********`), never a real credential value, in both the failure case and the normal-print case.

## 6. Example template is complete (validates US4, FR-007, SC-005)

```sh
diff <(grep -oE '^[A-Z_]+__?[A-Z_]*' .env.example | sort -u) \
     <(uv run python -c "
from app.core.config import Settings
import json
print('\n'.join(sorted(Settings.model_json_schema().get('$defs', {}))))
")  # illustrative — actual script lives in tasks.md; the point is zero diff
```

**Expected**: no variable required by `Settings` is missing from `.env.example`, and no stale variable remains in `.env.example` that `Settings` no longer reads.

## 7. Cross-repo consistency (validates contract §4)

```sh
cd ../nbe-financial-advisor-backend/deploy
docker compose up --build ai-service
```

**Expected**: builds and starts `ai-service` successfully using this deploy repo's own `.env`/`docker-compose.yml`, which now uses the same renamed `GROUP__FIELD` keys as this repo — confirms the two-repo rename in contract §4 landed in both places, not just this repo.
