# Quickstart: Validating LLM Observability with Langfuse

Validates the feature end-to-end against the acceptance scenarios in [spec.md](spec.md) and the contracts in [contracts/observability-config.md](contracts/observability-config.md). Assumes the implementation tasks (tasks.md, generated separately) are complete.

## Prerequisites

- Docker Compose, as already required to run this repo (`compose/docker-compose.yml`).
- A `.env` file copied from `.env.example`. `LANGFUSE_ENABLED=true` and the local-stack `LANGFUSE_HOST`/`PUBLIC_KEY`/`SECRET_KEY` pair are already the defaults — no editing needed for the common case in step 1 (contract §1).

## 1. Local self-hosted stack is opt-in; once enabled, tracing needs no further config (validates SC-003, US3-AS1, US3-AS2)

By default, the observability stack does **not** start — `docker compose -f compose/docker-compose.yml up --build` brings up `ai-service` and `mineru-server` only, with none of Langfuse's six containers running (US3-AS2). This keeps the base stack free of six extra containers for anyone not using local tracing. (`ai-service` itself still starts with `LANGFUSE_ENABLED=true` by default — it just fails open, silently, since nothing is listening at `LANGFUSE_HOST` yet; see step 5.)

To bring the local stack up, activate the `observability` compose profile — nothing else to configure, since `.env.example`'s defaults already match what `langfuse-web` seeds itself with:

```sh
docker compose -f compose/docker-compose.yml --profile observability up --build
# or: make dev-up-observability
```

**Expected**: `langfuse-web`, `langfuse-worker`, and their Postgres/ClickHouse/Redis/MinIO become healthy alongside `ai-service` and `mineru-server`, with no manual account, project, or API-key creation step anywhere — `langfuse-web` seeds its admin account/project/API-key pair on first boot via Langfuse's own [headless initialization](https://langfuse.com/self-hosting/administration/headless-initialization) (`LANGFUSE_INIT_*` vars in `compose/langfuse/docker-compose.yml`), from the exact same `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` values `ai-service` already authenticates with (US3-AS1). `http://localhost:3000` serves the Langfuse UI — log in with `LANGFUSE_INIT_USER_EMAIL`/`LANGFUSE_INIT_USER_PASSWORD` (defaults in `.env.example`) if you need to browse it; self-service signup is disabled by default (FR-007).

## 2. (Alternative) Point at a cloud-hosted Langfuse instead, or disable entirely

Set `LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in `.env` to a cloud instance's real values and skip the `observability` profile entirely — `docker compose -f compose/docker-compose.yml up --build` (no `--profile` flag) is then enough; `ai-service` sends traces there directly with no local Langfuse containers at all. To disable tracing outright regardless of what's running, set `LANGFUSE_ENABLED=false` — the three connection settings aren't required in that state.

**Note**: `LANGFUSE_ENABLED=true` (the default) with any of the three connection settings blank fails `ai-service`'s startup immediately (`app/core/config.py`, research.md §11) — this is different from step 1's "fails open" behavior, which only applies once startup has already succeeded with valid config and Langfuse itself just isn't reachable yet.

## 3. End-to-end trace capture (validates US1-AS1, US1-AS2, SC-001, SC-002)

1. Trigger any LLM-backed request against `ai-service` — e.g. a chat message through the existing chat endpoint, or a normalization run, using real (non-mock) LLM mode (`USE_MOCK_LLM=0`, since mock mode never calls a model and has nothing to trace).
2. Within 10 seconds, open the Langfuse UI's trace list.
3. **Expected**: a trace appears for that request, containing every LLM call made while handling it (e.g. all agent calls within one Maestro turn, or all chunk calls within one normalization run), in order, with inputs/outputs visible subject to the redaction rules from research.md §3.
4. Repeat with a multi-step pipeline (e.g. a multi-chunk normalization run) and confirm all calls nest under a single trace rather than appearing as unrelated entries (US1-AS2).

## 4. Failed LLM call is recorded, not dropped (validates US1-AS3, FR-008)

1. Trigger a request that causes an LLM call to fail or time out (e.g. point `OPENAI_BASE_URL` at an unreachable host temporarily, or use an existing failure-injection test fixture if one exists).
2. **Expected**: the trace still appears in Langfuse, with the failed step marked as errored rather than silently missing.

## 5. Fail-open: Langfuse down never breaks a request (validates FR-005, SC-004)

```sh
docker compose -f compose/docker-compose.yml stop langfuse-web langfuse-worker
```

1. Trigger the same LLM-backed request as in step 3.
2. **Expected**: the request completes successfully with its normal response — no error, no added latency beyond normal variance. No trace appears (expected, since the backend is down), but nothing in the response or logs indicates a user-facing failure.
3. Restart Langfuse (`docker compose -f compose/docker-compose.yml start langfuse-web langfuse-worker`) and confirm subsequent requests resume producing traces.

## 6. Persistence across restarts (validates US3-AS3, FR-004)

```sh
docker compose -f compose/docker-compose.yml restart langfuse-web langfuse-worker postgres clickhouse redis minio
```
(Use the Langfuse-owned `postgres`/`clickhouse`/`redis`/`minio` services from `compose/langfuse/docker-compose.yml`, not the AI service's own `postgres`.)

**Expected**: traces recorded before the restart are still visible in the Langfuse UI afterward.

## 7. Usage/cost dashboard (validates US2-AS1, US2-AS2, SC-005)

1. After steps 3–4 have produced traces across more than one feature (e.g. one chat trace, one normalization trace).
2. Open Langfuse's usage/dashboard view, select a time range covering the test traces.
3. **Expected**: token and request counts are visible, filterable/groupable by the originating feature or flow (via the span attributes each trace carries), without needing to query `ai-service`'s own logs or database.
